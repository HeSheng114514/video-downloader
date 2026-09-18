# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""数据模型：媒体信息与下载任务。"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_ids = itertools.count(1)


class TaskState(str, Enum):
    PENDING = "等待解析"
    PARSING = "解析中"
    READY = "等待下载"
    DOWNLOADING = "下载中"
    MERGING = "合并中"
    PAUSED = "已暂停"
    DONE = "已完成"
    ERROR = "失败"
    CANCELED = "已取消"

    @property
    def is_finished(self) -> bool:
        return self in (TaskState.DONE, TaskState.ERROR, TaskState.CANCELED)

    @property
    def is_active(self) -> bool:
        return self in (TaskState.PARSING, TaskState.DOWNLOADING, TaskState.MERGING)


@dataclass
class MediaInfo:
    """解析结果。"""
    url: str
    platform: str = "other"
    title: str = ""
    uploader: str = ""
    duration: float = 0.0
    thumbnail: str = ""
    webpage_url: str = ""
    ext: str = "mp4"
    filesize: int = 0
    direct_url: str = ""          # 自研引擎解析出的直链
    headers: dict = field(default_factory=dict)   # 直链下载所需请求头
    formats: list = field(default_factory=list)
    is_playlist: bool = False
    playlist_count: int = 1
    extra: dict = field(default_factory=dict)

    def describe(self) -> str:
        from .utils import human_bytes, human_duration

        bits = [self.title or self.url]
        if self.duration:
            bits.append(human_duration(self.duration))
        if self.filesize:
            bits.append(human_bytes(self.filesize))
        return " · ".join(bits)


@dataclass
class DownloadTask:
    url: str
    id: int = field(default_factory=lambda: next(_ids))
    platform: str = "other"
    state: TaskState = TaskState.PENDING
    info: MediaInfo | None = None
    title: str = ""
    progress: float = 0.0        # 0-100
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: float = 0.0
    filepath: str = ""
    error: str = ""
    engine: str = ""
    added_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    retries: int = 0
    overwrite: bool = False      # 明确要求覆盖下载（同名文件将被替换）

    # 运行期控制
    cancel_event: object | None = field(default=None, repr=False, compare=False)
    proc: object | None = field(default=None, repr=False, compare=False)

    @property
    def key(self) -> str:
        """视频唯一标识，用于查重（同一视频的不同链接形式会得到相同 key）。"""
        from .platforms import video_key

        return video_key(self.url)

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.info and self.info.title:
            return self.info.title
        return self.url

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or time.time()
        return end - self.started_at

    def to_row(self) -> dict:
        from .platforms import PLATFORMS
        from .utils import human_bytes, human_eta, human_speed, make_progress_bar, shorten

        plat = PLATFORMS.get(self.platform, PLATFORMS["other"])
        prog = self.progress
        if self.state == TaskState.DONE:
            bar = make_progress_bar(100)
        elif self.state in (TaskState.PENDING, TaskState.PARSING):
            bar = "—"
        else:
            bar = make_progress_bar(prog)
        size = human_bytes(self.total or (self.info.filesize if self.info else 0))
        got = human_bytes(self.downloaded) if self.downloaded else "-"
        return {
            "id": str(self.id),
            "platform": plat["short"],
            "title": shorten(self.display_title, 70),
            "progress": bar,
            "speed": human_speed(self.speed) if self.state == TaskState.DOWNLOADING else "-",
            "size": f"{got} / {size}" if self.downloaded else size,
            "eta": human_eta(self.eta) if self.state == TaskState.DOWNLOADING else "-",
            "state": self.error if self.state == TaskState.ERROR else self.state.value,
            "path": str(Path(self.filepath).parent) if self.filepath else "",
        }
