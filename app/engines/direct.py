# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""直链媒体下载器：抖音/快手等自研引擎解析出直链后，用它落盘。"""
from __future__ import annotations

import time
from pathlib import Path

from ..models import MediaInfo
from ..utils import safe_filename, unique_path
from .base import BaseEngine, EngineCancelled, EngineContext, EngineError


def build_target_path(info: MediaInfo, ctx: EngineContext, index: int | None = None) -> Path:
    """根据标题生成保存路径。"""
    outdir = ctx.config.output_dir(info.platform)
    outdir.mkdir(parents=True, exist_ok=True)
    title = safe_filename(info.title or "未命名视频")
    if index is not None:
        title = f"{title}_{index:02d}"
    ext = (info.ext or "mp4").lstrip(".")
    path = outdir / f"{title}.{ext}"
    if ctx.config.keep_original:
        path = unique_path(path)
    return path


def download_direct(info: MediaInfo, ctx: EngineContext, url: str | None = None,
                    index: int | None = None) -> Path:
    """下载直链到本地，带进度/取消/断点续传。"""
    media_url = url or info.direct_url
    if not media_url:
        raise EngineError("未解析到可下载的视频地址")
    dst = build_target_path(info, ctx, index)
    ctx.log(f"开始下载：{dst.name}")

    last = {"t": 0.0}

    def on_prog(done: int, total: int, speed: float) -> None:
        ctx.on_progress(done, total, speed)

    try:
        ctx.client.download(
            media_url,
            dst,
            headers=info.headers or {},
            on_progress=on_prog,
            cancel=ctx.cancel,
            resume=True,
            mobile=False,
            max_retries=max(2, ctx.config.retries),
        )
    except EngineError:
        raise
    except Exception as e:
        if ctx.cancelled():
            raise EngineCancelled("任务已取消")
        msg = str(e)
        if "已取消" in msg:
            raise EngineCancelled("任务已取消")
        raise EngineError(f"下载失败：{msg[:160]}")
    ctx.on_file(str(dst))
    return dst


class DirectEngine(BaseEngine):
    """通用直链引擎（保留给 .mp4/.m3u8 等直接输入）。"""

    key = "direct"
    name = "直链"

    def can_handle(self, url: str) -> bool:
        return bool(url.lower().split("?")[0].endswith((".mp4", ".m4v", ".mov", ".flv", ".mkv", ".webm", ".mp3", ".m4a")))

    def probe(self, url: str, ctx: EngineContext) -> MediaInfo:
        name = url.split("?")[0].rsplit("/", 1)[-1] or "直链媒体"
        return MediaInfo(url=url, platform="other", title=name, direct_url=url, ext=name.rsplit(".", 1)[-1])

    def download(self, url: str, info: MediaInfo, ctx: EngineContext) -> Path:
        return download_direct(info, ctx)
