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

# 哔哩哔哩
BILI_ID_PATTERNS = [
    re.compile(r"bilibili\.com/video/(BV[0-9A-Za-z]{10})", re.I),
    re.compile(r"bilibili\.com/video/av(\d+)", re.I),
    re.compile(r"[?&]bvid=(BV[0-9A-Za-z]{10})", re.I),
]
BILI_SHORT = re.compile(r"https?://b23\.tv/[A-Za-z0-9]+", re.I)

# YouTube
YT_ID_PATTERNS = [
    re.compile(r"youtu\.be/([A-Za-z0-9_\-]{6,})", re.I),
    re.compile(r"[?&]v=([A-Za-z0-9_\-]{6,})", re.I),
    re.compile(r"youtube\.com/(?:shorts|embed|live)/([A-Za-z0-9_\-]{6,})", re.I),
]


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
    return bool(DY_SHORT.match(url) or KS_SHORT.match(url) or BILI_SHORT.match(url))


def extract_bilibili_id(url: str) -> str | None:
    for pat in BILI_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def extract_youtube_id(url: str) -> str | None:
    for pat in YT_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def video_key(url: str) -> str:
    """把同一视频的不同链接形式归一成同一个 key，用于「查重」。

    例如下面三个链接会得到同一个 key::

        https://www.bilibili.com/video/BV1GJ411x7h7
        https://www.bilibili.com/video/BV1GJ411x7h7?spm_id_from=333.999
        https://bilibili.com/video/BV1GJ411x7h7/

    无法识别作品号时退化为「去掉查询参数与末尾斜杠的 URL」。
    """
    u = (url or "").strip()
    if not u:
        return ""
    platform = detect_platform(u)
    try:
        if platform == "bilibili":
            vid = extract_bilibili_id(u)
            if vid:
                return f"bilibili:{vid.lower()}"
        elif platform == "douyin":
            vid = extract_douyin_id(u)
            if vid:
                return f"douyin:{vid}"
        elif platform == "kuaishou":
            pid = extract_kuaishou_id(u)
            if pid:
                return f"kuaishou:{pid}"
        elif platform == "youtube":
            vid = extract_youtube_id(u)
            if vid:
                return f"youtube:{vid}"
        elif platform == "tiktok":
            m = re.search(r"/video/(\d{6,})", u)
            if m:
                return f"tiktok:{m.group(1)}"
    except Exception:
        pass
    base = re.sub(r"[?#].*$", "", u).rstrip("/")
    return (base or u).lower()


SUPPORTED_HINT = "哔哩哔哩 · 抖音 · 快手 · TikTok · YouTube · 小红书 · 微博 · 西瓜视频 等 1000+ 站点"
