# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""引擎注册与选择。

针对不同平台选择「主力引擎 + 兜底引擎」：
* 抖音：无 Cookie 时用自研解析（无需登录），配置了 Cookie 时优先 yt-dlp
* 快手：yt-dlp 不支持，使用自研 GraphQL 解析
* 其他（B站/YouTube/TikTok/…）：yt-dlp
"""
from __future__ import annotations

from ..config import Config
from ..platforms import (detect_platform, extract_bilibili_id, extract_douyin_id,
                         extract_kuaishou_id, video_key)
from .base import BaseEngine, EngineContext, EngineError
from .direct import DirectEngine
from .douyin import DouyinEngine
from .kuaishou import KuaishouEngine
from .ytdlp import YtDlpEngine

_ytdlp = YtDlpEngine()
_douyin = DouyinEngine()
_kuaishou = KuaishouEngine()
_direct = DirectEngine()


def all_engines() -> dict[str, BaseEngine]:
    return {"ytdlp": _ytdlp, "douyin": _douyin, "kuaishou": _kuaishou, "direct": _direct}


def get_engine(key: str) -> BaseEngine:
    return all_engines().get(key, _ytdlp)


def has_cookies(cfg: Config) -> bool:
    from pathlib import Path

    return bool(cfg.cookies_from_browser.strip()
                or (cfg.cookies_file.strip() and Path(cfg.cookies_file).is_file()))


def normalize_url(url: str, client, log=None) -> str:
    """把分享短链归一化为标准详情页地址。

    * 抖音：v.douyin.com/xxx → www.douyin.com/video/{id}
    * 快手：v.kuaishou.com/xxx → www.kuaishou.com/short-video/{id}
    * B 站：b23.tv/xxx → www.bilibili.com/video/{BV}

    归一化还有一个好处：查重更准确——短链与长链会被识别成同一个视频。
    """
    platform = detect_platform(url)
    if platform == "bilibili":
        vid = extract_bilibili_id(url)
        if not vid:
            try:
                vid = extract_bilibili_id(client.resolve_redirect(url, timeout=15))
            except Exception:
                vid = None
        if vid:
            return f"https://www.bilibili.com/video/{vid}"
    if platform == "douyin":
        vid = extract_douyin_id(url)
        if not vid:
            # 短链需跟随跳转；部分分享链会跳到 /share/forward/{id}/
            try:
                vid = extract_douyin_id(client.resolve_redirect(url, mobile=True))
            except Exception:
                vid = None
        if not vid:
            try:
                vid = extract_douyin_id(client.get(url, mobile=True, timeout=20).url)
            except Exception:
                vid = None
        if vid:
            return f"https://www.douyin.com/video/{vid}"
    elif platform == "kuaishou":
        pid = extract_kuaishou_id(url)
        if not pid:
            try:
                pid = extract_kuaishou_id(client.resolve_redirect(url, mobile=True))
            except Exception:
                pid = None
        if pid:
            return f"https://www.kuaishou.com/short-video/{pid}"
    return url


def engines_for(url: str, cfg: Config) -> list[BaseEngine]:
    """返回按优先级排序、可用于该链接的引擎列表。"""
    platform = detect_platform(url)
    chain: list[BaseEngine] = []
    if platform == "douyin":
        chain = [_ytdlp, _douyin] if has_cookies(cfg) else [_douyin, _ytdlp]
    elif platform == "kuaishou":
        chain = [_kuaishou, _ytdlp]
    elif _direct.can_handle(url):
        chain = [_direct, _ytdlp]
    else:
        chain = [_ytdlp]
    return [e for e in chain if e.can_handle(url)]
