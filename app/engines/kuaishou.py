# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""快手解析引擎（多策略）。

yt-dlp 目前不支持快手，因此这里自行实现三条解析路径：
A. 移动端分享页（服务端渲染，通常内嵌无水印直链 srcNoMark）
B. 快手 Web GraphQL（visionVideoDetail，可能触发验证码，需要登录 Cookie）
C. 短链详情页 og:video 元信息兜底
"""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from ..models import MediaInfo
from ..platforms import detect_platform, extract_kuaishou_id
from .base import BaseEngine, EngineContext, EngineError
from .direct import download_direct
from .douyin import read_cookie_header

GRAPHQL_URL = "https://www.kuaishou.com/graphql"

DETAIL_QUERY = """
query visionVideoDetail($photoId: String, $page: String, $webPageArea: String) {
  visionVideoDetail(photoId: $photoId, page: $page, webPageArea: $webPageArea) {
    status
    author { id name }
    photo {
      id duration caption timestamp
      photoUrl
      photoH265Url { url }
      mainMvUrls { url }
      manifest { adaptationSet { representation { url height width avgBitrate } } }
      coverUrl
    }
  }
}
"""

URL_PATTERNS = [
    re.compile(r'"srcNoMark"\s*:\s*"(https?:[^"]+)"'),
    re.compile(r'"photoUrl"\s*:\s*"(https?:[^"]+)"'),
    re.compile(r'"playUrl"\s*:\s*"(https?:[^"]+)"'),
    re.compile(r'"url"\s*:\s*"(https?://[^"]*?\.mp4[^"]*)"'),
    re.compile(r"<meta[^>]+property=[\"']og:video[\"'][^>]+content=[\"']([^\"']+)[\"']", re.I),
    re.compile(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']og:video[\"']", re.I),
]


def _unescape(url: str) -> str:
    return url.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")


class KuaishouEngine(BaseEngine):
    key = "kuaishou"
    name = "快手解析"

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == "kuaishou"

    # ------------------------------------------------------------ 解析
    def probe(self, url: str, ctx: EngineContext) -> MediaInfo:
        photo_id = extract_kuaishou_id(url)
        if not photo_id:
            resolved = ctx.client.resolve_redirect(url, mobile=True)
            photo_id = extract_kuaishou_id(resolved)
        if not photo_id:
            raise EngineError("无法识别快手作品 ID（支持 v.kuaishou.com 短链与 kuaishou.com/short-video/xxx）")

        cookie = read_cookie_header(ctx.config.cookies_file, "kuaishou")
        errors: list[str] = []
        for name, fetch in (
            ("移动分享页", self._mobile_page),
            ("GraphQL 接口", self._graphql),
            ("网页元信息", self._web_meta),
        ):
            try:
                ctx.log(f"快手：尝试{name}")
                data = fetch(photo_id, cookie, ctx)
                if data and data.get("direct_url"):
                    info = self._to_info(url, photo_id, data)
                    ctx.log(f"快手：{name}解析成功")
                    return info
                errors.append(f"{name}：未取到播放地址")
            except EngineError as e:
                errors.append(f"{name}：{e}")
            except Exception as e:
                errors.append(f"{name}：{type(e).__name__}")
        raise EngineError(
            "快手解析失败（" + "；".join(errors[-2:]) + "）。"
            "如提示验证码，请在「设置 → 网络」中选择浏览器 Cookie（浏览器需已登录快手）后重试"
        )

    # ------------------------------------------------------------ 策略 A
    def _mobile_page(self, photo_id: str, cookie: str, ctx: EngineContext) -> dict:
        headers = {"Referer": "https://www.kuaishou.com/"}
        if cookie:
            headers["Cookie"] = cookie
        for tmpl in (
            "https://v.m.chenzhongtech.com/fw/photo/{id}",
            "https://m.gifshow.com/fw/photo/{id}",
            "https://v.m.kuaishou.com/fw/photo/{id}",
        ):
            target = tmpl.format(id=photo_id)
            try:
                resp = ctx.client.get(target, headers=headers, mobile=True, timeout=20)
            except Exception:
                continue
            html = resp.text
            found = self._extract_media(html)
            if found:
                return {"direct_url": found, "html": html}
            # INIT_STATE / 内嵌 JSON
            m = re.search(r"window\.INIT_STATE\s*=\s*(\{.*?\})\s*;?\s*</script>", html, re.S)
            if m:
                try:
                    payload = json.loads(m.group(1))
                    data = self._dig(payload)
                    if data:
                        return data
                except Exception:
                    pass
        raise EngineError("移动端页面未包含直链")

    def _dig(self, payload) -> dict | None:
        """在嵌套 JSON 中寻找视频地址。"""
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in ("srcNoMark", "photoUrl", "playUrl", "url", "src"):
                    val = node.get(key)
                    if isinstance(val, str) and val.startswith("http") and (
                            ".mp4" in val or "video" in val or "ndc" in val or "yximgs" in val):
                        return {"direct_url": _unescape(val)}
                manifest = node.get("manifest")
                if isinstance(manifest, dict):
                    got = self._from_manifest(manifest)
                    if got:
                        return got
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        return None

    @staticmethod
    def _from_manifest(manifest: dict) -> dict | None:
        reps: list[tuple[int, str]] = []
        for aset in manifest.get("adaptationSet") or []:
            for rep in aset.get("representation") or []:
                url = rep.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    reps.append((int(rep.get("avgBitrate") or rep.get("height") or 0), url))
        if reps:
            reps.sort(key=lambda x: x[0], reverse=True)
            return {"direct_url": reps[0][1]}
        return None

    @staticmethod
    def _extract_media(html: str) -> str:
        best = ""
        for pat in URL_PATTERNS:
            for m in pat.finditer(html):
                url = _unescape(m.group(1))
                if not url.startswith("http"):
                    continue
                if "srcNoMark" in pat.pattern or ".mp4" in url:
                    return url
                best = best or url
        return best

    # ------------------------------------------------------------ 策略 B
    def _graphql(self, photo_id: str, cookie: str, ctx: EngineContext) -> dict:
        did = self._did_from_cookie(cookie)
        headers = {
            "Referer": "https://www.kuaishou.com/",
            "Origin": "https://www.kuaishou.com",
            "Content-Type": "application/json",
        }
        headers["Cookie"] = cookie or f"did={did}"
        payload = {
            "operationName": "visionVideoDetail",
            "variables": {"photoId": photo_id, "page": "detail", "webPageArea": ""},
            "query": DETAIL_QUERY,
        }
        resp = ctx.client.post_json(GRAPHQL_URL, payload, headers=headers, timeout=25)
        text = resp.text
        if "Need captcha" in text or "captcha" in text.lower():
            raise EngineError("触发验证码校验，需要登录 Cookie")
        data = json.loads(text)
        if data.get("errors"):
            msg = data["errors"][0].get("message", "")
            if "Cannot query field" in msg or "GRAPHQL_VALIDATION" in str(data["errors"][0].get("extensions", {})):
                raise EngineError("接口字段变更：" + msg[:60])
            raise EngineError(msg[:80])
        detail = (data.get("data") or {}).get("visionVideoDetail") or {}
        photo = detail.get("photo") or {}
        direct = ""
        for key in ("photoUrl", "photoH265Url", "mainMvUrls"):
            val = photo.get(key)
            if isinstance(val, str) and val.startswith("http"):
                direct = val
                break
            if isinstance(val, dict) and isinstance(val.get("url"), str):
                direct = val["url"]
                break
            if isinstance(val, list):
                for entry in val:
                    if isinstance(entry, dict) and isinstance(entry.get("url"), str):
                        direct = entry["url"]
                        break
            if direct:
                break
        if not direct and isinstance(photo.get("manifest"), dict):
            got = self._from_manifest(photo["manifest"])
            direct = (got or {}).get("direct_url", "")
        return {
            "direct_url": direct,
            "title": photo.get("caption") or "",
            "author": (detail.get("author") or {}).get("name") or "",
            "duration": (float(photo.get("duration") or 0) / 1000.0) if photo.get("duration") else 0.0,
            "thumbnail": photo.get("coverUrl") or "",
        }

    @staticmethod
    def _did_from_cookie(cookie: str) -> str:
        m = re.search(r"did=([^;]+)", cookie or "")
        if m:
            return m.group(1)
        import random
        import string

        return "web_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=32))

    # ------------------------------------------------------------ 策略 C
    def _web_meta(self, photo_id: str, cookie: str, ctx: EngineContext) -> dict:
        headers = {"Referer": "https://www.kuaishou.com/"}
        if cookie:
            headers["Cookie"] = cookie
        for target in (
            f"https://www.kuaishou.com/short-video/{photo_id}",
            f"https://www.kuaishou.com/f/{photo_id}",
        ):
            try:
                resp = ctx.client.get(target, headers=headers, timeout=20)
            except Exception:
                continue
            html = resp.text
            direct = self._extract_media(html)
            title = ""
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
                title = re.sub(r"[-_|]\s*快手.*$", "", title).strip()
            if direct:
                return {"direct_url": direct, "title": title}
        raise EngineError("网页中未找到视频地址")

    # ------------------------------------------------------------ 转换/下载
    @staticmethod
    def _to_info(url: str, photo_id: str, data: dict) -> MediaInfo:
        info = MediaInfo(url=url, platform="kuaishou", ext="mp4")
        info.title = (data.get("title") or f"快手视频_{photo_id}").strip()
        info.uploader = data.get("author") or ""
        info.duration = float(data.get("duration") or 0)
        info.thumbnail = data.get("thumbnail") or ""
        info.direct_url = data.get("direct_url") or ""
        info.webpage_url = f"https://www.kuaishou.com/short-video/{photo_id}"
        info.headers = {
            "Referer": "https://www.kuaishou.com/",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
        }
        return info

    def download(self, url: str, info: MediaInfo, ctx: EngineContext) -> Path:
        if not info.direct_url:
            fresh = self.probe(url, ctx)
            info.direct_url = fresh.direct_url
            info.headers = fresh.headers or info.headers
            info.title = info.title or fresh.title
        ctx.on_status("下载中")
        return download_direct(info, ctx)
