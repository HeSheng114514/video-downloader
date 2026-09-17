# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""配置管理：config.json 读写 + 默认值。"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import paths

# 画质档位 -> 显示名 / yt-dlp 格式选择器
QUALITY_PRESETS: list[tuple[str, str, str]] = [
    ("best", "最佳画质（自动）", "bv*+ba/b"),
    ("2160", "4K 2160P", "bv*[height<=2160]+ba/b[height<=2160]"),
    ("1440", "2K 1440P", "bv*[height<=1440]+ba/b[height<=1440]"),
    ("1080", "1080P 高清", "bv*[height<=1080]+ba/b[height<=1080]"),
    ("720", "720P 普清", "bv*[height<=720]+ba/b[height<=720]"),
    ("480", "480P 流畅", "bv*[height<=480]+ba/b[height<=480]"),
    ("audio", "仅音频（提取音乐）", "bv*+ba/b"),
]

QUALITY_KEYS = [q[0] for q in QUALITY_PRESETS]
QUALITY_LABELS = {q[0]: q[1] for q in QUALITY_PRESETS}
QUALITY_FORMATS = {q[0]: q[2] for q in QUALITY_PRESETS}

BROWSERS = ["", "chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi", "safari"]


@dataclass
class Config:
    # ---- 常规
    download_dir: str = ""
    quality: str = "best"
    audio_only: bool = False
    audio_format: str = "mp3"          # mp3 / m4a / flac / wav
    audio_quality: str = "0"           # 0 最好
    subdir_per_platform: bool = False  # 按平台建子文件夹

    # ---- 下载行为
    concurrency: int = 2               # 同时下载任务数
    concurrent_fragments: int = 4      # 单任务分片并发
    retries: int = 10
    speed_limit: str = ""              # 例如 5M / 800K，空=不限速
    playlist: bool = True              # 允许下载整个合集/列表
    playlist_items: str = ""           # 例如 1-10
    prefer_mp4: bool = True            # 合并/转封装为 mp4
    write_thumbnail: bool = False      # 保存封面图
    embed_thumbnail: bool = False      # 嵌入封面
    embed_metadata: bool = False       # 嵌入元数据
    write_subtitles: bool = False      # 下载字幕
    auto_subtitle: bool = False        # 自动字幕
    sponsorblock: bool = False         # 跳过赞助片段
    filename_template: str = "%(title).120B.%(ext)s"
    keep_original: bool = True         # 保留原始文件（不覆盖）

    # ---- 网络
    proxy: str = ""                    # http://127.0.0.1:7890
    cookies_from_browser: str = ""     # chrome / edge / firefox ...
    cookies_file: str = ""             # cookies.txt
    manual_cookies: dict = field(default_factory=dict)   # {域名: "a=b; c=d"} 手动填写的 Cookie
    user_agent: str = ""               # 留空使用默认
    insecure: bool = False             # 忽略 SSL 证书错误

    # ---- 界面
    theme: str = "light"               # light / dark
    show_log: bool = True
    auto_parse: bool = True            # 粘贴后自动解析
    clipboard_watch: bool = False      # 监听剪贴板
    close_to_tray: bool = False

    # ---- 高级
    keep_ytdlp_updated: bool = True
    last_update_check: str = ""
    window_geometry: str = ""
    extra_ytdlp_args: str = ""

    # ---------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        p = path or paths.config_file()
        cfg = cls()
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                valid = {f.name for f in fields(cls)}
                for k, v in raw.items():
                    if k in valid:
                        setattr(cfg, k, v)
            except Exception:
                pass
        if not cfg.download_dir:
            cfg.download_dir = str(paths.default_download_dir())
        # 类型纠正
        for name in ("concurrency", "concurrent_fragments", "retries"):
            try:
                setattr(cfg, name, max(1, int(getattr(cfg, name))))
            except Exception:
                setattr(cfg, name, 2)
        if cfg.quality not in QUALITY_KEYS:
            cfg.quality = "best"
        # manual_cookies 必须是 {域名: cookie 字符串}
        if not isinstance(cfg.manual_cookies, dict):
            cfg.manual_cookies = {}
        else:
            cfg.manual_cookies = {str(k): str(v) for k, v in cfg.manual_cookies.items() if k and v}
        return cfg

    def save(self, path: Path | None = None) -> None:
        p = path or paths.config_file()
        try:
            p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------------------------------------------------------------
    @property
    def format_selector(self) -> str:
        if self.audio_only:
            return "ba/b"
        return QUALITY_FORMATS.get(self.quality, "bv*+ba/b")

    def output_dir(self, platform_key: str = "") -> Path:
        base = Path(self.download_dir or paths.default_download_dir())
        if self.subdir_per_platform and platform_key:
            from .platforms import PLATFORMS

            name = PLATFORMS.get(platform_key, {}).get("name", platform_key)
            base = base / str(name)
        base.mkdir(parents=True, exist_ok=True)
        return base


class ConfigStore:
    """线程安全的全局配置容器。"""

    _lock = threading.RLock()
    _config: Config | None = None

    @classmethod
    def get(cls) -> Config:
        with cls._lock:
            if cls._config is None:
                cls._config = Config.load()
            return cls._config

    @classmethod
    def reload(cls) -> Config:
        with cls._lock:
            cls._config = Config.load()
            return cls._config

    @classmethod
    def save(cls) -> None:
        with cls._lock:
            if cls._config:
                cls._config.save()
