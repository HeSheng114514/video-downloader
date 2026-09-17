# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""抖音解析引擎（多策略）。

抖音 Web 接口由 Argus 风控保护，纯匿名请求会被拦截（403 Uifid Not Found），
因此采用「多策略 + 明确指引」：

策略 A：移动端 IES 接口（部分视频仍可用，无需登录）
策略 B：Web 详情接口（携带 cookies.txt，或依赖 yt-dlp 的浏览器 Cookie）
策略 C：分享页 / 移动分享页 HTML 解析

若全部失败，则给出「请在设置中导入浏览器 Cookie」的明确提示，
并由 yt-dlp 引擎（原生支持抖音 + 浏览器 Cookie）继续兜底。
"""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from ..cookies import read_cookie_header
from ..models import MediaInfo
from ..platforms import detect_platform, extract_douyin_id
from .base import BaseEngine, EngineContext, EngineError
from .direct import download_direct

WEB_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "190500",
    "version_name": "19.5.0",
    "cookie_enabled": "true",
    "screen_width": "1920",
    "screen_height": "1080",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Chrome",
    "browser_version": "122.0.0.0",
    "browser_online": "true",
    "engine_name": "Blink",
    "engine_version": "122.0.0.0",
    "os_name": "Windows",
    "os_version": "10",
    "cpu_core_num": "8",
    "device_memory": "8",
    "platform": "PC",
    "downlink": "10",
    "effective_type": "4g",
    "round_trip_time": "50",
}


class DouyinEngine(BaseEngine):
    key = "douyin"
    name = "抖音解析"

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == "douyin"

    # ------------------------------------------------------------ 元数据
    def probe(self, url: str, ctx: EngineContext) -> MediaInfo:
        video_id = extract_douyin_id(url)
        if not video_id:
            resolved = ctx.client.resolve_redirect(url, mobile=True)
            video_id = extract_douyin_id(resolved)
        if not video_id:
            raise EngineError("无法从链接中识别抖音视频 ID（支持 v.douyin.com 短链与 douyin.com/video/xxx）")

        cookie = read_cookie_header(ctx.config.cookies_file, "douyin")
        errors: list[str] = []
        for name, fetch in (
            ("IES 移动接口", self._api_ies_mobile),
            ("Web 详情接口", self._api_web_detail),
            ("分享页解析", self._share_page),
        ):
            try:
                ctx.log(f"抖音：尝试{name}")
                data = fetch(video_id, cookie, ctx)
                info = self._build_info(url, video_id, data)
                if info and info.direct_url:
                    ctx.log(f"抖音：{name}解析成功")
                    return info
                errors.append(f"{name}：未取到播放地址")
            except EngineError as e:
                errors.append(f"{name}：{e}")
            except Exception as e:
                errors.append(f"{name}：{type(e).__name__}")
        raise EngineError(
            "抖音解析失败（" + "；".join(errors[-2:]) + "）。"
            "抖音已启用风控，请在「设置 → 网络」中选择浏览器 Cookie（浏览器需已登录抖音）后重试"
        )

    # ------------------------------------------------------------ 策略实现
    def _headers(self, ctx: EngineContext, cookie: str = "", mobile: bool = False) -> dict:
        h = {
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
        }
        if cookie:
            h["Cookie"] = cookie
        return h

    def _api_ies_mobile(self, video_id: str, cookie: str, ctx: EngineContext) -> dict:
        resp = ctx.client.get(
            f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={video_id}",
            headers=self._headers(ctx, cookie), mobile=True, timeout=20,
        )
        text = resp.text.strip()
        if not text:
            raise EngineError("接口返回空数据")
        data = json.loads(text)
        items = data.get("item_list") or []
        if not items:
            raise EngineError("未返回视频数据")
        return {"item": items[0]}

    def _api_web_detail(self, video_id: str, cookie: str, ctx: EngineContext) -> dict:
        query = urllib.parse.urlencode({"aweme_id": video_id, **WEB_PARAMS})
        resp = ctx.client.get(
            f"https://www.douyin.com/aweme/v1/web/aweme/detail/?{query}",
            headers=self._headers(ctx, cookie), timeout=25,
        )
        text = resp.text.strip()
        if not text.startswith("{"):
            raise EngineError("接口被风控拦截")
        data = json.loads(text)
        detail = data.get("aweme_detail")
        if not detail:
            raise EngineError("未返回视频数据（通常需要登录 Cookie）")
        return {"item": detail}

    def _share_page(self, video_id: str, cookie: str, ctx: EngineContext) -> dict:
        for share_url in (
            f"https://www.iesdouyin.com/share/video/{video_id}/",
            f"https://www.douyin.com/share/video/{video_id}",
        ):
            try:
                resp = ctx.client.get(share_url, headers=self._headers(ctx, cookie), mobile=True, timeout=20)
            except Exception:
                continue
            html = resp.text
            m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", html, re.S)
            if m:
                try:
                    data = json.loads(m.group(1))
                    page = (data.get("loaderData") or {}).get("video_(id)/page") or {}
                    res = page.get("videoInfoRes") or {}
                    items = res.get("item_list") or []
                    if items:
                        return {"item": items[0]}
                except Exception:
                    pass
            # 兼容旧版 RENDER_DATA
            m = re.search(r'<script id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.S)
            if m:
                try:
                    payload = json.loads(urllib.parse.unquote(m.group(1)))
                    for value in payload.values():
                        items = (value or {}).get("aweme", {}).get("detail") if isinstance(value, dict) else None
                        if items:
                            return {"item": items}
                except Exception:
                    pass
        raise EngineError("页面中未找到视频数据")

    # ------------------------------------------------------------ 数据转换
    @staticmethod
    def _build_info(url: str, video_id: str, payload: dict) -> MediaInfo:
        item = payload.get("item") or {}
        info = MediaInfo(url=url, platform="douyin", ext="mp4")
        info.title = (item.get("desc") or item.get("aweme_id") or video_id).strip()
        author = item.get("author") or {}
        info.uploader = author.get("nickname") or ""
        video = item.get("video") or {}
        info.duration = float(video.get("duration") or item.get("duration") or 0) / 1000.0
        cover = video.get("cover") or video.get("origin_cover") or {}
        if isinstance(cover, dict):
            urls = cover.get("url_list") or []
            info.thumbnail = urls[0] if urls else ""
        info.webpage_url = f"https://www.douyin.com/video/{video_id}"

        candidates: list[tuple[int, str]] = []
        # 无水印播放地址
        for key in ("play_addr", "play_addr_h264", "play_addr_265", "download_addr"):
            addr = video.get(key) or {}
            for u in (addr.get("url_list") or []):
                if isinstance(u, str) and u.startswith("http"):
                    u = u.replace("playwm", "play").replace("/play/", "/play/")
                    candidates.append((int(addr.get("data_size") or 0), u))
        # 多码率
        for br in (video.get("bit_rate") or []):
            addr = br.get("play_addr") or {}
            for u in (addr.get("url_list") or []):
                if isinstance(u, str) and u.startswith("http"):
                    candidates.append((int(br.get("bit_rate") or 0), u))
        if not candidates:
            return info
        candidates.sort(key=lambda x: x[0], reverse=True)
        info.direct_url = candidates[0][1]
        info.filesize = candidates[0][0]
        info.headers = {
            "Referer": "https://www.douyin.com/",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
        }
        return info

    # ------------------------------------------------------------ 下载
    def download(self, url: str, info: MediaInfo, ctx: EngineContext) -> Path:
        if not info.direct_url:
            fresh = self.probe(url, ctx)
            info.direct_url = fresh.direct_url
            info.headers = fresh.headers or info.headers
            info.title = info.title or fresh.title
        ctx.on_status("下载中")
        return download_direct(info, ctx)
