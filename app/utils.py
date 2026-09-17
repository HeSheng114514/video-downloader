# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""通用工具函数。"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------- 子进程

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def popen_kwargs() -> dict:
    """统一的子进程参数：Windows 下隐藏黑框。"""
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
    return kw


def run_hidden(cmd: list[str], timeout: int | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        cwd=cwd,
        **popen_kwargs(),
    )


def open_folder(path: str | Path) -> None:
    """在资源管理器中打开目录并选中文件（若为文件）。"""
    p = Path(path)
    if p.is_file():
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))  # type: ignore[attr-defined]


# ---------------------------------------------------------------- 文本/URL

URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff\"'<>()\[\]{}，。、；：！？]+", re.I)


def extract_urls(text: str) -> list[str]:
    """从任意文本（分享文案）中提取所有 http(s) 链接，去重保序。"""
    if not text:
        return []
    # 分享文案里常有「复制此链接，打开抖音」等中文，URL_RE 已按中文边界切分
    found = URL_RE.findall(text)
    cleaned: list[str] = []
    for u in found:
        u = u.strip().rstrip(".,;:")
        if u and u not in cleaned:
            cleaned.append(u)
    return cleaned


def looks_like_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))


_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


def safe_filename(name: str, maxlen: int = 120) -> str:
    """把任意标题转成 Windows 合法文件名。"""
    if not name:
        return "未命名"
    name = unicodedata.normalize("NFC", name)
    name = _ILLEGAL.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip(" .")
    return name or "未命名"


def human_bytes(n: float | int | None) -> str:
    if not n or n <= 0:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    n = float(n)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}" if i else f"{int(n)} B"


def human_speed(n: float | None) -> str:
    if not n or n <= 0:
        return "-"
    return human_bytes(n) + "/s"


def human_eta(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def human_duration(seconds: float | int | None) -> str:
    if not seconds:
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def make_progress_bar(percent: float, width: int = 12) -> str:
    percent = max(0.0, min(100.0, percent or 0.0))
    filled = int(round(percent / 100 * width))
    return "█" * filled + "░" * (width - filled) + f" {percent:5.1f}%"


def unique_path(path: Path) -> Path:
    """若文件已存在，自动加 (1)(2) 后缀，避免覆盖。"""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for i in range(1, 1000):
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    return path


def shorten(text: str, n: int = 60) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def flatten(items: Iterable[Iterable[str]]) -> list[str]:
    out: list[str] = []
    for it in items:
        out.extend(it)
    return out
