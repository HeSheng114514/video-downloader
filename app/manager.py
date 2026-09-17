# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""任务调度：解析 / 下载 / 并发 / 暂停 / 重试。

设计：
* 固定数量 worker 线程消费任务队列（并发数可动态调整）
* 每个任务的「解析 → 下载」在同一个 worker 中串行完成
* 引擎链式兜底：主力引擎失败自动尝试备用引擎
* 所有状态变化通过事件回调抛给 UI 线程
"""
from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Callable

from . import bootstrap, paths
from .config import Config, ConfigStore
from .engines import engines_for, get_engine, normalize_url
from .engines.base import EngineCancelled, EngineContext, EngineError
from .models import DownloadTask, MediaInfo, TaskState
from .net import shared_client
from .platforms import detect_platform, platform_name
from .utils import extract_urls, human_bytes

EventCB = Callable[[str, dict], None]


class TaskManager:
    def __init__(self, emit: EventCB, config: Config | None = None):
        self.emit = emit
        self.config = config or ConfigStore.get()
        self.tasks: list[DownloadTask] = []
        self._lock = threading.RLock()
        self._jobs: deque[tuple[int, str]] = deque()
        self._job_event = threading.Event()
        self._workers: list[threading.Thread] = []
        self._running = True
        self._active = 0
        self.stats = {"done": 0, "error": 0, "bytes": 0}
        self._start_workers()

    # ------------------------------------------------------------ worker
    def _start_workers(self) -> None:
        want = max(1, int(self.config.concurrency or 2))
        while len(self._workers) < want:
            t = threading.Thread(target=self._worker, name=f"dl-worker-{len(self._workers)+1}", daemon=True)
            t.start()
            self._workers.append(t)

    def _worker(self) -> None:
        while self._running:
            job = None
            with self._lock:
                if self._jobs:
                    job = self._jobs.popleft()
            if job is None:
                self._job_event.wait(0.4)
                self._job_event.clear()
                continue
            task_id, action = job
            task = self.get(task_id)
            if task is None or task.state == TaskState.CANCELED:
                continue
            try:
                if action == "parse":
                    self._do_parse(task)
                else:
                    self._do_download(task)
            except EngineCancelled:
                self._set_state(task, TaskState.CANCELED, "已取消")
            except EngineError as e:
                self._fail(task, str(e))
            except Exception as e:  # 未预期异常
                self._fail(task, f"{type(e).__name__}: {e}")
                self._log("error", traceback.format_exc()[:800])
            finally:
                self._job_event.set()

    # ------------------------------------------------------------ 任务管理
    def add_urls(self, text: str | list[str], auto_parse: bool = True) -> list[DownloadTask]:
        urls = extract_urls(text) if isinstance(text, str) else list(text)
        added: list[DownloadTask] = []
        with self._lock:
            existing = {t.url for t in self.tasks}
            for u in urls:
                if u in existing:
                    continue
                task = DownloadTask(url=u, platform=detect_platform(u))
                self.tasks.append(task)
                added.append(task)
        for task in added:
            self.emit("task_added", {"task": task})
            if auto_parse:
                self.enqueue(task.id, "parse")
        if added:
            self._log("info", f"已添加 {len(added)} 个任务")
        return added

    def get(self, task_id: int) -> DownloadTask | None:
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    return t
        return None

    def enqueue(self, task_id: int, action: str = "download") -> None:
        task = self.get(task_id)
        if task is None:
            return
        if action == "parse":
            self._set_state_raw(task, TaskState.PENDING)
        with self._lock:
            self._jobs.append((task_id, action))
        self._job_event.set()

    def enqueue_all(self, action: str = "download") -> int:
        count = 0
        for t in list(self.tasks):
            if t.state == TaskState.CANCELED:
                continue
            if action == "download" and t.state == TaskState.DONE:
                continue
            self.enqueue(t.id, action)
            count += 1
        return count

    def pause(self, task_id: int) -> None:
        task = self.get(task_id)
        if task is None:
            return
        if task.cancel_event:
            task.cancel_event.set()  # type: ignore[union-attr]
        if task.proc is not None:
            proc = task.proc
            try:
                import subprocess

                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            except Exception:
                pass
        self._set_state(task, TaskState.PAUSED, "已暂停")

    def cancel(self, task_id: int) -> None:
        task = self.get(task_id)
        if task is None:
            return
        task.retries = 0
        if task.cancel_event:
            task.cancel_event.set()  # type: ignore[union-attr]
        if task.proc is not None:
            proc = task.proc
            try:
                import subprocess

                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            except Exception:
                pass
        self._set_state(task, TaskState.CANCELED, "已取消")

    def retry(self, task_id: int) -> None:
        task = self.get(task_id)
        if task is None:
            return
        task.error = ""
        task.retries += 1
        if task.info is None:
            self.enqueue(task_id, "parse")
        else:
            self.enqueue(task_id, "download")

    def remove(self, task_id: int) -> None:
        self.cancel(task_id)
        with self._lock:
            self.tasks = [t for t in self.tasks if t.id != task_id]
        self.emit("task_removed", {"id": task_id})

    def clear_finished(self) -> None:
        with self._lock:
            keep = [t for t in self.tasks if not t.state.is_finished]
            removed = [t.id for t in self.tasks if t.state.is_finished]
            self.tasks = keep
        for rid in removed:
            self.emit("task_removed", {"id": rid})

    def set_concurrency(self, n: int) -> None:
        self.config.concurrency = max(1, int(n))
        self._start_workers()

    def shutdown(self) -> None:
        self._running = False
        self._job_event.set()
        for t in list(self.tasks):
            if t.state.is_active:
                self.cancel(t.id)

    # ------------------------------------------------------------ 内部
    def _ctx(self, task: DownloadTask) -> EngineContext:
        client = shared_client(self.config.proxy, self.config.insecure, self.config.user_agent)
        cancel = threading.Event()
        task.cancel_event = cancel
        ctx = EngineContext(
            config=self.config,
            client=client,
            log=lambda m, _t=task: self._log("info", f"[{_t.id}] {m}"),
            on_status=lambda s, _t=task: self._status(_t, s),
            on_progress=lambda d, tot, sp, _t=task: self._progress(_t, d, tot, sp),
            on_file=lambda p, _t=task: self._file(_t, p),
            on_proc=lambda p, _t=task: setattr(_t, "proc", p),
            cancel=cancel,
        )
        return ctx

    def _do_parse(self, task: DownloadTask) -> None:
        self._set_state(task, TaskState.PARSING, "解析中")
        ctx = self._ctx(task)
        # 分享短链归一化（抖音/快手），便于 yt-dlp 接手
        try:
            normalized = normalize_url(task.url, ctx.client, ctx.log)
            if normalized and normalized != task.url:
                ctx.log(f"链接已归一化：{normalized}")
                task.url = normalized
        except Exception:
            pass
        engines = engines_for(task.url, self.config)
        if not engines:
            raise EngineError("暂不支持该链接")
        errors: list[str] = []
        for engine in engines:
            if ctx.cancelled():
                raise EngineCancelled("已取消")
            try:
                info = engine.probe(task.url, ctx)
                if not info.title:
                    info.title = task.url
                task.info = info
                task.title = info.title
                task.platform = info.platform or task.platform
                task.engine = engine.key
                if info.is_playlist:
                    task.total = 0
                self._set_state(task, TaskState.READY, "等待下载")
                self.emit("task_parsed", {"task": task, "info": info})
                self._log("success", f"[{task.id}] 解析成功：{info.title[:60]}")
                return
            except EngineCancelled:
                raise
            except EngineError as e:
                errors.append(f"{engine.name}: {e}")
                self._log("warn", f"[{task.id}] {engine.name} 解析失败：{e}")
            except Exception as e:
                errors.append(f"{engine.name}: {e}")
                self._log("warn", f"[{task.id}] {engine.name} 异常：{type(e).__name__} {e}")
        raise EngineError(self._pick_error(errors))

    def _do_download(self, task: DownloadTask) -> None:
        ctx = self._ctx(task)
        engines = engines_for(task.url, self.config)
        if not engines:
            raise EngineError("暂不支持该链接")
        if task.info is None:
            self._do_parse(task)
            ctx = self._ctx(task)
        assert task.info is not None
        task.started_at = time.time()
        task.finished_at = 0.0
        task.error = ""
        self._set_state(task, TaskState.DOWNLOADING, "下载中")
        errors: list[str] = []
        for engine in engines:
            if ctx.cancelled():
                raise EngineCancelled("已取消")
            try:
                task.engine = engine.key
                path = engine.download(task.url, task.info, ctx)
                task.filepath = str(path)
                task.progress = 100.0
                task.speed = 0.0
                task.finished_at = time.time()
                self.stats["done"] += 1
                self._set_state(task, TaskState.DONE, "已完成")
                self._log("success", f"[{task.id}] 下载完成：{path.name}")
                self.emit("task_done", {"task": task, "path": str(path)})
                return
            except EngineCancelled:
                raise
            except EngineError as e:
                errors.append(f"{engine.name}: {e}")
                self._log("warn", f"[{task.id}] {engine.name} 失败：{e}")
                if ctx.cancelled():
                    raise EngineCancelled("已取消")
            except Exception as e:
                errors.append(f"{engine.name}: {e}")
                self._log("warn", f"[{task.id}] {engine.name} 异常：{type(e).__name__} {e}")
        raise EngineError(self._pick_error(errors))

    @staticmethod
    def _pick_error(errors: list[str]) -> str:
        """从各引擎的错误中挑出对用户最有指导意义的一条。

        平台专用解析引擎（抖音/快手）的提示通常比 yt-dlp 的通用报错更有用，
        例如「需要配置 Cookie / 触发验证码」。
        """
        if not errors:
            return "操作失败"
        for e in errors:
            if any(k in e for k in ("Cookie", "cookie", "验证码", "风控", "登录")):
                return e
        for e in errors:
            if not e.startswith("yt-dlp"):
                return e
        return errors[-1]

    # ------------------------------------------------------------ 事件
    def _set_state_raw(self, task: DownloadTask, state: TaskState) -> None:
        task.state = state
        self.emit("task_update", {"task": task})

    def _set_state(self, task: DownloadTask, state: TaskState, status: str = "") -> None:
        task.state = state
        self.emit("task_update", {"task": task})

    def _status(self, task: DownloadTask, status: str) -> None:
        self.emit("task_update", {"task": task})

    def _progress(self, task: DownloadTask, done: int, total: int, speed: float) -> None:
        task.downloaded = done
        if total:
            task.total = total
            task.progress = min(99.9, done * 100.0 / total)
        task.speed = speed
        if speed and total and done:
            task.eta = max(0.0, (total - done) / speed)
        self.emit("task_progress", {"task": task})

    def _file(self, task: DownloadTask, path: str) -> None:
        task.filepath = path
        try:
            task.downloaded = Path(path).stat().st_size
        except Exception:
            pass
        self.emit("task_update", {"task": task})

    def _fail(self, task: DownloadTask, message: str) -> None:
        task.error = message
        task.finished_at = time.time()
        self.stats["error"] += 1
        self._set_state(task, TaskState.ERROR, message)
        self._log("error", f"[{task.id}] {message}")

    def _log(self, level: str, message: str) -> None:
        self.emit("log", {"level": level, "message": message})
