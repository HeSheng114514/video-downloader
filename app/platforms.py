# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""平台识别与链接归一化。"""
from __future__ import annotations

import re

# 平台注册表：key -> 展示信息
PLATFORMS: dict[str, dict] = {
    "bilibili": {"name": "哔哩哔哩", "short": "B站", "color": "#fb7299", "engine": "ytdlp"},
    "douyin": {"name": "抖音", "short": "抖音", "color": "#000000", "engine": "douyin"},
    "kuaishou": {"name": "快手", "short": "快手", "color": "#ff4906", "engine": "kuaishou"},
    "tiktok": {"name": "TikTok", "short": "TikTok", "color": "#25f4ee", "engine": "ytdlp"},
    "youtube": {"name": "YouTube", "short": "YT", "color": "#ff0000", "engine": "ytdlp"},
    "twitter": {"name": "X / Twitter", "short": "X", "color": "#1d9bf0", "engine": "ytdlp"},
    "instagram": {"name": "Instagram", "short": "IG", "color": "#e1306c", "engine": "ytdlp"},
    "xiaohongshu": {"name": "小红书", "short": "小红书", "color": "#fe2c55", "engine": "ytdlp"},
    "weibo": {"name": "微博", "short": "微博", "color": "#e6162d", "engine": "ytdlp"},
    "xigua": {"name": "西瓜视频", "short": "西瓜", "color": "#f85959", "engine": "ytdlp"},
    "youku": {"name": "优酷", "short": "优酷", "color": "#1eb8ff", "engine": "ytdlp"},
    "iqiyi": {"name": "爱奇艺", "short": "爱奇艺", "color": "#00be06", "engine": "ytdlp"},
    "tencent": {"name": "腾讯视频", "short": "腾讯", "color": "#ff7f00", "engine": "ytdlp"},
    "facebook": {"name": "Facebook", "short": "FB", "color": "#1877f2", "engine": "ytdlp"},
    "twitch": {"name": "Twitch", "short": "Twitch", "color": "#9146ff", "engine": "ytdlp"},
    "vimeo": {"name": "Vimeo", "short": "Vimeo", "color": "#1ab7ea", "engine": "ytdlp"},
    "pornhub": {"name": "Pornhub", "short": "PH", "color": "#f90", "engine": "ytdlp"},
    "other": {"name": "其他站点", "short": "其他", "color": "#6b7280", "engine": "ytdlp"},
}

# 域名 -> 平台
_DOMAIN_MAP: list[tuple[str, str]] = [
    ("bilibili.com", "bilibili"),
    ("b23.tv", "bilibili"),
    ("douyin.com", "douyin"),
    ("iesdouyin.com", "douyin"),
    ("amemv.com", "douyin"),
    ("kuaishou.com", "kuaishou"),
    ("chenzhongtech.com", "kuaishou"),
    ("gifshow.com", "kuaishou"),
    ("tiktok.com", "tiktok"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("twitter.com", "twitter"),
    ("x.com", "twitter"),
    ("instagram.com", "instagram"),
    ("xiaohongshu.com", "xiaohongshu"),
    ("xhslink.com", "xiaohongshu"),
    ("weibo.com", "weibo"),
    ("weibo.cn", "weibo"),
    ("ixigua.com", "xigua"),
    ("youku.com", "youku"),
    ("iqiyi.com", "iqiyi"),
    ("v.qq.com", "tencent"),
    ("facebook.com", "facebook"),
    ("fb.watch", "facebook"),
    ("twitch.tv", "twitch"),
    ("vimeo.com", "vimeo"),
    ("pornhub.com", "pornhub"),
]

# 抖音
DY_SHORT = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_\-]+", re.I)
DY_ID_PATTERNS = [
    re.compile(r"douyin\.com/video/(\d{15,25})", re.I),
    re.compile(r"douyin\.com/note/(\d{15,25})", re.I),
    re.compile(r"douyin\.com/(?:share/)?(?:video|note|slides|forward)/(\d{15,25})", re.I),
    re.compile(r"iesdouyin\.com/share/(?:video|note|slides|forward)/(\d{15,25})", re.I),
    re.compile(r"[?&]modal_id=(\d{15,25})", re.I),
    re.compile(r"[?&]aweme_id=(\d{15,25})", re.I),
    # 兜底：douyin.com 下任意路径中的 19 位作品 ID（排除用户主页）
    re.compile(r"douyin\.com/(?!user/)[\w\-/]*?(\d{15,25})", re.I),
]
# 快手
KS_ID_PATTERNS = [
    re.compile(r"kuaishou\.com/short-video/([A-Za-z0-9_\-]{6,})", re.I),
    re.compile(r"kuaishou\.com/f/([A-Za-z0-9_\-]{6,})", re.I),
    re.compile(r"chenzhongtech\.com/fw/photo/([A-Za-z0-9_\-]{6,})", re.I),
    re.compile(r"gifshow\.com/fw/photo/([A-Za-z0-9_\-]{6,})", re.I),
    re.compile(r"kuaishou\.com/profile/[^/]+/([A-Za-z0-9_\-]{6,})", re.I),
    re.compile(r"[?&]photoId=([A-Za-z0-9_\-]{6,})", re.I),
]
KS_SHORT = re.compile(r"https?://v\.kuaishou\.com/[A-Za-z0-9_\-]+", re.I)
KS_LIVE_SHORT = re.compile(r"https?://(?:v\.)?kuaishou\.com/[A-Za-z0-9_\-]+", re.I)


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "", re.I)
    return (m.group(1) if m else "").lower().lstrip("www.")


def detect_platform(url: str) -> str:
    host = domain_of(url)
    if not host:
        return "other"
    for dom, key in _DOMAIN_MAP:
        if host == dom or host.endswith("." + dom) or host.endswith(dom):
            return key
    return "other"


def platform_name(key: str) -> str:
    return PLATFORMS.get(key, PLATFORMS["other"])["name"]


def extract_douyin_id(url: str) -> str | None:
    for pat in DY_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def extract_kuaishou_id(url: str) -> str | None:
    for pat in KS_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def is_short_link(url: str) -> bool:
    return bool(DY_SHORT.match(url) or KS_SHORT.match(url))


SUPPORTED_HINT = "哔哩哔哩 · 抖音 · 快手 · TikTok · YouTube · 小红书 · 微博 · 西瓜视频 等 1000+ 站点"
