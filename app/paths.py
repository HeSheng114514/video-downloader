# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""视频下载器 —— 路径与运行环境解析

同时兼容三种运行方式：
1. 源码运行（python run.py）
2. PyInstaller 单文件打包（exe）
3. PyInstaller 目录模式打包
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "视频下载器"
APP_ID = "VideoDownloader"
APP_VERSION = "1.0.0"
ORG_NAME = "DSH"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境中。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """只读资源根目录（打包后为解包临时目录 _MEIPASS）。"""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _writable(base: Path) -> bool:
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def app_root() -> Path:
    """可写数据根目录（配置、bin、日志）。

    优先使用程序自身目录（绿色版体验），不可写时退回用户目录。
    """
    if is_frozen():
        candidate = Path(sys.executable).resolve().parent
    else:
        candidate = Path(__file__).resolve().parent.parent
    if _writable(candidate):
        return candidate
    fallback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_ID
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def bin_dir() -> Path:
    d = app_root() / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return app_root() / "config.json"


def temp_dir() -> Path:
    d = app_root() / ".cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_temp_dir(prefix: str = "tmp_") -> Path:
    """在缓存目录下创建唯一的临时目录。

    不使用 tempfile.mkdtemp：部分受限环境下其创建出的目录不可写。
    """
    import random
    import string

    base = temp_dir()
    for _ in range(50):
        name = prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        path = base / name
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:
            continue
    path = base / (prefix + "fallback")
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    d = app_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_download_dir() -> Path:
    """默认下载目录：系统「下载」文件夹下的子目录。"""
    for key in ("USERPROFILE",):
        base = os.environ.get(key)
        if base:
            p = Path(base) / "Downloads" / "视频下载"
            return p
    return Path.home() / "Downloads" / "视频下载"


def ensure_dirs() -> None:
    for d in (bin_dir(), temp_dir(), log_dir()):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def ytdlp_path() -> Path:
    return bin_dir() / "yt-dlp.exe"


def ffmpeg_path() -> Path:
    return bin_dir() / "ffmpeg.exe"


def ffprobe_path() -> Path:
    return bin_dir() / "ffprobe.exe"


def find_ffmpeg() -> Path | None:
    """查找可用的 ffmpeg：优先自带 bin 目录，其次系统 PATH。"""
    local = ffmpeg_path()
    if local.is_file():
        return local
    import shutil

    found = shutil.which("ffmpeg")
    return Path(found) if found else None
