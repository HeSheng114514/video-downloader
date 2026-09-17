# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""轻量 HTTP 客户端（仅依赖标准库）。

提供：
* 统一的 UA / 代理 / SSL 处理
* GET / POST-JSON / 短链重定向解析
* 带进度回调、断点续传、可取消的流式下载
"""
from __future__ import annotations

import gzip
import io
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

ProgressCB = Callable[[int, int, float], None]   # downloaded, total, speed


class HttpError(Exception):
    def __init__(self, message: str, status: int = 0, body: bytes = b""):
        super().__init__(message)
        self.status = status
        self.body = body


class SourceTooSlow(Exception):
    """下载源速度过慢（由进度回调主动抛出，用于自动切换镜像）。"""


@dataclass
class Response:
    status: int
    url: str
    headers: dict
    body: bytes

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("Content-Type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        for enc in (charset, "utf-8", "gbk", "latin-1"):
            try:
                return self.body.decode(enc)
            except Exception:
                continue
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


def _build_ssl(insecure: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class HttpClient:
    def __init__(
        self,
        proxy: str = "",
        insecure: bool = False,
        user_agent: str = "",
        timeout: float = 30.0,
        retries: int = 3,
    ):
        self.proxy = (proxy or "").strip()
        self.insecure = insecure
        self.ua = user_agent or DEFAULT_UA
        self.timeout = timeout
        self.retries = max(1, retries)
        self._ssl = _build_ssl(insecure)
        handlers: list[urllib.request.BaseHandler] = [urllib.request.HTTPSHandler(context=self._ssl)]
        if self.proxy:
            handlers.append(urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
        else:
            handlers.append(urllib.request.ProxyHandler())  # 使用系统代理设置
        self.opener = urllib.request.build_opener(*handlers)
        self.opener.addheaders = []

    # ------------------------------------------------------------ 基础请求
    def _headers(self, extra: dict | None = None, mobile: bool = False) -> dict:
        h = {
            "User-Agent": MOBILE_UA if mobile else self.ua,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close",
        }
        if extra:
            h.update({k: v for k, v in extra.items() if v is not None})
        return h

    @staticmethod
    def _decode(resp) -> bytes:
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
        try:
            if "gzip" in enc:
                return gzip.decompress(raw)
            if "deflate" in enc:
                try:
                    return zlib.decompress(raw)
                except zlib.error:
                    return zlib.decompress(raw, -zlib.MAX_WBITS)
        except Exception:
            return raw
        return raw

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: dict | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
        mobile: bool = False,
        allow_redirects: bool = True,
    ) -> Response:
        last_err: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(
                    url, data=data, headers=self._headers(headers, mobile), method=method
                )
                if not allow_redirects:
                    class _NoRedirect(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self, *a, **kw):
                            return None

                    opener = urllib.request.build_opener(
                        _NoRedirect(), urllib.request.HTTPSHandler(context=self._ssl)
                    )
                    if self.proxy:
                        opener.add_handler(urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
                else:
                    opener = self.opener
                with opener.open(req, timeout=timeout or self.timeout) as resp:
                    return Response(resp.status, resp.geturl(), dict(resp.headers), self._decode(resp))
            except urllib.error.HTTPError as e:
                body = b""
                try:
                    body = e.read()
                except Exception:
                    pass
                if e.code in (301, 302, 303, 307, 308) and not allow_redirects:
                    return Response(e.code, e.headers.get("Location", ""), dict(e.headers), body)
                last_err = HttpError(f"HTTP {e.code} {e.reason}", e.code, body)
                if e.code in (400, 401, 403, 404, 410):
                    raise last_err
            except Exception as e:  # 网络错误
                last_err = e
            time.sleep(0.6 * (attempt + 1))
        if isinstance(last_err, HttpError):
            raise last_err
        raise HttpError(f"请求失败：{last_err}")

    def get(self, url: str, headers: dict | None = None, **kw) -> Response:
        return self.request(url, "GET", headers, **kw)

    def post_json(self, url: str, payload: dict, headers: dict | None = None, **kw) -> Response:
        h = {"Content-Type": "application/json"}
        if headers:
            h.update(headers)
        return self.request(url, "POST", h, json.dumps(payload).encode("utf-8"), **kw)

    def resolve_redirect(self, url: str, headers: dict | None = None, max_hops: int = 6,
                         mobile: bool = False) -> str:
        """跟随短链，返回最终 URL（不下载正文）。"""
        current = url
        for _ in range(max_hops):
            try:
                resp = self.request(current, "GET", headers, allow_redirects=False,
                                    timeout=15, mobile=mobile)
            except HttpError as e:
                if e.status in (301, 302, 303, 307, 308):
                    current = e.body.decode("utf-8", "ignore") or current
                    continue
                raise
            if resp.status in (301, 302, 303, 307, 308) and resp.url:
                current = urllib.parse.urljoin(current, resp.url)
                continue
            return resp.url or current
        return current

    # ------------------------------------------------------------ 流式下载
    def download(
        self,
        url: str,
        dst: Path,
        headers: dict | None = None,
        on_progress: ProgressCB | None = None,
        cancel: threading.Event | None = None,
        resume: bool = True,
        mobile: bool = False,
        max_retries: int = 5,
        chunked: bool = True,
    ) -> Path:
        """带断点续传与进度回调的下载。

        默认走「分块下载」：以固定大小 Range 请求逐块写入，
        对长连接被中断/限速的网络环境（代理、CDN 掐连接）更加稳定。
        """
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if chunked:
            part = dst.with_suffix(dst.suffix + ".part")
            try:
                return self._download_chunked(url, dst, headers, on_progress, cancel, mobile)
            except SourceTooSlow:
                raise
            except HttpError:
                raise
            except Exception:
                # 分块成功写入过数据才退回流式下载；完全没数据说明源不可用，直接上抛
                if not (part.exists() and part.stat().st_size > 0):
                    raise
        return self._download_stream(url, dst, headers, on_progress, cancel, resume, mobile, max_retries)

    # -------------------------------------------------------- 分块下载
    def _probe_size(self, url: str, headers: dict | None, mobile: bool) -> tuple[int, str]:
        hdr = dict(headers or {})
        hdr["Range"] = "bytes=0-0"
        req = urllib.request.Request(url, headers=self._headers(hdr, mobile))
        with self.opener.open(req, timeout=self.timeout) as resp:
            final = resp.geturl() or url
            crange = resp.headers.get("Content-Range") or ""
            if "/" in crange:
                try:
                    return int(crange.rsplit("/", 1)[1]), final
                except ValueError:
                    pass
            length = int(resp.headers.get("Content-Length") or 0)
            return length, final

    def _download_chunked(
        self,
        url: str,
        dst: Path,
        headers: dict | None,
        on_progress: ProgressCB | None,
        cancel: threading.Event | None,
        mobile: bool = False,
        chunk_size: int = 1024 * 1024,
        max_retries: int = 6,
    ) -> Path:
        total, final_url = self._probe_size(url, headers, mobile)
        part = dst.with_suffix(dst.suffix + ".part")
        pos = part.stat().st_size if part.exists() else 0
        if total and pos > total:
            pos = 0
        start = time.time()
        base = pos
        with open(part, "r+b" if pos else "wb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise HttpError("已取消")
                if total and pos >= total:
                    break
                end = (pos + chunk_size - 1) if total else (pos + chunk_size - 1)
                if total:
                    end = min(end, total - 1)
                data = None
                last_err: Exception | None = None
                for attempt in range(max_retries):
                    if cancel is not None and cancel.is_set():
                        raise HttpError("已取消")
                    try:
                        hdr = dict(headers or {})
                        hdr["Range"] = f"bytes={pos}-{end}"
                        req = urllib.request.Request(final_url, headers=self._headers(hdr, mobile))
                        with self.opener.open(req, timeout=self.timeout) as resp:
                            data = resp.read()
                        if total and len(data) != end - pos + 1:
                            raise IOError(f"分块长度异常 {len(data)}")
                        break
                    except Exception as e:  # noqa: PERF203
                        last_err = e
                        data = None
                        time.sleep(0.5 * (attempt + 1))
                if data is None:
                    raise HttpError(f"分块下载失败：{last_err}")
                f.seek(pos)
                f.write(data)
                f.flush()
                pos += len(data)
                if not total and len(data) < chunk_size:
                    break
                if on_progress:
                    elapsed = max(1e-6, time.time() - start)
                    on_progress(pos, total, (pos - base) / elapsed)
        if total and part.stat().st_size < total:
            raise HttpError("下载不完整")
        if dst.exists():
            dst.unlink()
        part.replace(dst)
        return dst

    # -------------------------------------------------------- 流式下载
    def _download_stream(
        self,
        url: str,
        dst: Path,
        headers: dict | None,
        on_progress: ProgressCB | None,
        cancel: threading.Event | None,
        resume: bool = True,
        mobile: bool = False,
        max_retries: int = 5,
    ) -> Path:
        part = dst.with_suffix(dst.suffix + ".part") if resume else dst
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            have = part.stat().st_size if (resume and part.exists()) else 0
            hdr = dict(headers or {})
            if have:
                hdr["Range"] = f"bytes={have}-"
            try:
                req = urllib.request.Request(url, headers=self._headers(hdr, mobile))
                with self.opener.open(req, timeout=self.timeout) as resp:
                    total = int(resp.headers.get("Content-Length") or 0)
                    if have and resp.status != 206:
                        have = 0  # 服务器不支持续传
                    total = total + have
                    mode = "ab" if have else "wb"
                    start = time.time()
                    base = have
                    with open(part, mode) as f:
                        while True:
                            if cancel is not None and cancel.is_set():
                                raise HttpError("已取消")
                            chunk = resp.read(262144)
                            if not chunk:
                                break
                            f.write(chunk)
                            have += len(chunk)
                            if on_progress:
                                elapsed = max(1e-6, time.time() - start)
                                on_progress(have, total, (have - base) / elapsed)
                if total and part.stat().st_size < total:
                    raise HttpError("下载不完整，重试中")
                if part != dst:
                    if dst.exists():
                        dst.unlink()
                    part.replace(dst)
                return dst
            except HttpError:
                raise
            except Exception as e:
                if cancel is not None and cancel.is_set():
                    raise HttpError("已取消")
                if attempt >= max_retries:
                    raise HttpError(f"下载失败：{e}")
                time.sleep(1.2 * attempt)
        raise HttpError("下载失败")

    def close(self) -> None:
        pass


_shared_lock = threading.Lock()
_shared: dict[tuple, HttpClient] = {}


def shared_client(proxy: str = "", insecure: bool = False, user_agent: str = "") -> HttpClient:
    key = (proxy or "", bool(insecure), user_agent or "")
    with _shared_lock:
        client = _shared.get(key)
        if client is None:
            client = HttpClient(proxy=proxy, insecure=insecure, user_agent=user_agent)
            _shared[key] = client
        return client
