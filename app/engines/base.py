# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""引擎基类与运行上下文。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import Config
from ..models import MediaInfo
from ..net import HttpClient


@dataclass
class EngineContext:
    """传递给引擎的运行期上下文（回调 + 控制）。"""

    config: Config
    client: HttpClient
    log: Callable[[str], None] = lambda m: None
    on_status: Callable[[str], None] = lambda s: None
    on_progress: Callable[[int, int, float], None] = lambda d, t, s: None
    on_file: Callable[[str], None] = lambda p: None
    on_meta: Callable[[MediaInfo], None] = lambda m: None
    on_proc: Callable[[object], None] = lambda p: None
    cancel: threading.Event = field(default_factory=threading.Event)

    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise EngineCancelled("任务已取消")


class EngineError(Exception):
    """引擎可预期的失败（用于展示给用户）。"""


class EngineCancelled(EngineError):
    pass


class BaseEngine:
    key = "base"
    name = "基础引擎"

    def can_handle(self, url: str) -> bool:
        return True

    def probe(self, url: str, ctx: EngineContext) -> MediaInfo:
        raise NotImplementedError

    def download(self, url: str, info: MediaInfo, ctx: EngineContext) -> Path:
        raise NotImplementedError
