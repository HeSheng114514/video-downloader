# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""主窗口。"""
from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import bootstrap, paths
from ..config import QUALITY_LABELS, QUALITY_PRESETS, ConfigStore
from ..manager import TaskManager
from ..models import DownloadTask, TaskState
from ..platforms import SUPPORTED_HINT
from ..utils import extract_urls, open_folder
from .settings import SettingsDialog
from .theme import apply_theme

APP_TITLE = f"视频下载器 v{paths.APP_VERSION}"


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = ConfigStore.get()
        self.events: queue.Queue = queue.Queue()
        self.rows: dict[int, str] = {}
        self.colors = apply_theme(self, self.cfg.theme)
        self.manager = TaskManager(self._post_event, self.cfg)

        self.title(APP_TITLE)
        geometry = self.cfg.window_geometry or "1180x760"
        self.geometry(geometry)
        self.minsize(980, 640)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._last_clip = ""
        self._last_clip_check = 0.0
        self._env_ready = False
        self._build_ui()
        self.after(120, self._pump)
        self.after(400, self._startup_check)

    # ================================================================ UI
    def _build_ui(self) -> None:
        c = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._build_header()
        self._build_input()
        self._build_tasks()
        self._build_log()
        self._build_status()

    # ---------------------------------------------------------- 顶部
    def _build_header(self) -> None:
        c = self.colors
        bar = ttk.Frame(self, style="Panel.TFrame", padding=(14, 10))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        left = ttk.Frame(bar, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="w")
        ttk.Label(left, text="🎬 视频下载器", style="Title.TLabel").pack(side="left")
        ttk.Label(left, text=f"   {SUPPORTED_HINT}", style="PanelDim.TLabel").pack(side="left", padx=(6, 0))

        right = ttk.Frame(bar, style="Panel.TFrame")
        right.grid(row=0, column=2, sticky="e")
        self.btn_env = ttk.Button(right, text="⚙ 运行环境", command=self._open_env_dialog)
        self.btn_env.pack(side="right", padx=(6, 0))
        ttk.Button(right, text="🛠 设置", command=self._open_settings).pack(side="right", padx=(6, 0))

        ttk.Separator(self, orient="horizontal").grid(row=0, column=0, sticky="sew")

    # ---------------------------------------------------------- 输入区
    def _build_input(self) -> None:
        c = self.colors
        wrap = ttk.Frame(self, padding=(14, 12, 14, 6))
        wrap.grid(row=1, column=0, sticky="ew")
        wrap.columnconfigure(0, weight=1)
        wrap.columnconfigure(1, weight=0)

        # 左：链接输入
        left = ttk.Labelframe(wrap, text=" 视频链接（每行一个，支持粘贴分享文案） ", padding=(10, 8))
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        self.txt_urls = tk.Text(left, height=4, wrap="none", relief="flat", font=("Consolas", 10),
                                bg=c["input_bg"], fg=c["text"], insertbackground=c["text"],
                                highlightthickness=1, highlightbackground=c["border"],
                                highlightcolor=c["accent"], undo=True)
        self.txt_urls.grid(row=0, column=0, sticky="nsew")
        self.txt_urls.bind("<Control-Return>", lambda e: self._on_parse())
        sb = ttk.Scrollbar(left, orient="vertical", command=self.txt_urls.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.txt_urls.configure(yscrollcommand=sb.set)

        btnrow = ttk.Frame(left)
        btnrow.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btnrow, text="📋 粘贴", command=self._paste).pack(side="left")
        ttk.Button(btnrow, text="🗑 清空", command=lambda: self.txt_urls.delete("1.0", "end")).pack(side="left", padx=4)
        ttk.Button(btnrow, text="🔍 解析", command=self._on_parse).pack(side="left", padx=4)
        ttk.Button(btnrow, text="⬇ 开始下载", style="Accent.TButton",
                   command=self._on_download).pack(side="left", padx=(12, 4))
        ttk.Label(btnrow, text="Ctrl+Enter 快速解析", style="Dim.TLabel").pack(side="right")

        # 右：常用选项
        right = ttk.Labelframe(wrap, text=" 下载选项 ", padding=(10, 8))
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        ttk.Label(right, text="画质").grid(row=0, column=0, sticky="w", pady=3)
        self.var_quality = tk.StringVar(value=QUALITY_LABELS.get(self.cfg.quality, "最佳画质（自动）"))
        self.cmb_quality = ttk.Combobox(right, textvariable=self.var_quality, state="readonly", width=20,
                                        values=[label for _, label, _ in QUALITY_PRESETS])
        self.cmb_quality.grid(row=0, column=1, sticky="ew", pady=3)
        self.cmb_quality.bind("<<ComboboxSelected>>", self._on_quality_change)

        self.var_audio = tk.BooleanVar(value=self.cfg.audio_only)
        ttk.Checkbutton(right, text="仅音频（提取 MP3）", variable=self.var_audio,
                        command=self._on_audio_toggle).grid(row=1, column=0, columnspan=2, sticky="w", pady=3)

        ttk.Label(right, text="保存到").grid(row=2, column=0, sticky="w", pady=3)
        self.var_dir = tk.StringVar(value=self.cfg.download_dir)
        ent = ttk.Entry(right, textvariable=self.var_dir, width=26)
        ent.grid(row=2, column=1, sticky="ew", pady=3)
        ent.bind("<FocusOut>", lambda e: self._apply_dir())
        ent.bind("<Return>", lambda e: self._apply_dir())
        ttk.Button(right, text="浏览…", command=self._choose_dir).grid(row=3, column=1, sticky="e", pady=(0, 4))

        row = ttk.Frame(right)
        row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Label(row, text="并发").pack(side="left")
        self.var_conc = tk.IntVar(value=self.cfg.concurrency)
        sp = ttk.Spinbox(row, from_=1, to=10, width=4, textvariable=self.var_conc, command=self._apply_concurrency)
        sp.pack(side="left", padx=(6, 12))
        self.var_proxy = tk.StringVar(value=self.cfg.proxy)
        ttk.Label(row, text="代理").pack(side="left")
        pe = ttk.Entry(row, textvariable=self.var_proxy, width=16)
        pe.pack(side="left", padx=(6, 0), fill="x", expand=True)
        pe.bind("<FocusOut>", lambda e: self._apply_proxy())
        pe.bind("<Return>", lambda e: self._apply_proxy())

        ttk.Label(right, text="YouTube/TikTok 等站点需要代理，如 http://127.0.0.1:7890",
                  style="Dim.TLabel", wraplength=260, justify="left").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))
        right.columnconfigure(1, weight=1)

    # ---------------------------------------------------------- 任务表
    def _build_tasks(self) -> None:
        c = self.colors
        frame = ttk.Frame(self, padding=(14, 0, 14, 6))
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        bar = ttk.Frame(frame)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="任务列表", style="Bold.TLabel").pack(side="left")
        self.lbl_count = ttk.Label(bar, text="共 0 个任务", style="Dim.TLabel")
        self.lbl_count.pack(side="left", padx=8)

        for text, cmd in (("清空已完成", self._clear_finished),
                          ("全部取消", self._cancel_all),
                          ("全部重试", self._retry_all),
                          ("打开目录", lambda: open_folder(self.cfg.download_dir))):
            ttk.Button(bar, text=text, style="Ghost.TButton", command=cmd).pack(side="right", padx=3)

        cols = ("id", "platform", "title", "progress", "speed", "size", "eta", "state")
        heads = {"id": "#", "platform": "平台", "title": "标题", "progress": "进度",
                 "speed": "速度", "size": "大小", "eta": "剩余", "state": "状态"}
        widths = {"id": 40, "platform": 62, "title": 380, "progress": 150,
                  "speed": 92, "size": 130, "eta": 66, "state": 150}

        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for col in cols:
            self.tree.heading(col, text=heads[col])
            self.tree.column(col, width=widths[col], anchor="w" if col in ("title", "state", "path") else "center",
                             stretch=(col == "title"))
        self.tree.grid(row=1, column=0, sticky="nsew")
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        vs.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vs.set)

        self.tree.tag_configure("done", foreground=c["success"])
        self.tree.tag_configure("error", foreground=c["error"])
        self.tree.tag_configure("active", foreground=c["info"])
        self.tree.tag_configure("paused", foreground=c["warn"])

        self.tree.bind("<Double-1>", self._on_row_double_click)
        self.tree.bind("<Button-3>", self._on_row_menu)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_buttons())

        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="打开文件", command=lambda: self._row_action("open_file"))
        self.menu.add_command(label="打开所在目录", command=lambda: self._row_action("open_dir"))
        self.menu.add_separator()
        self.menu.add_command(label="重新下载", command=lambda: self._row_action("retry"))
        self.menu.add_command(label="取消", command=lambda: self._row_action("cancel"))
        self.menu.add_separator()
        self.menu.add_command(label="复制链接", command=lambda: self._row_action("copy_url"))
        self.menu.add_command(label="复制标题", command=lambda: self._row_action("copy_title"))
        self.menu.add_separator()
        self.menu.add_command(label="移除任务", command=lambda: self._row_action("remove"))

    # ---------------------------------------------------------- 日志
    def _build_log(self) -> None:
        c = self.colors
        self.log_wrap = ttk.Frame(self, padding=(14, 0, 14, 6))
        self.log_wrap.grid(row=3, column=0, sticky="ew")
        self.log_wrap.columnconfigure(0, weight=1)

        head = ttk.Frame(self.log_wrap)
        head.grid(row=0, column=0, sticky="ew")
        self.var_show_log = tk.BooleanVar(value=self.cfg.show_log)
        ttk.Checkbutton(head, text="显示运行日志", variable=self.var_show_log,
                        command=self._toggle_log).pack(side="left")
        ttk.Button(head, text="清空日志", style="Ghost.TButton",
                   command=lambda: self._clear_log()).pack(side="right")

        self.log_box = tk.Text(self.log_wrap, height=7, wrap="word", relief="flat",
                               font=("Consolas", 9), bg=c["panel"], fg=c["text_dim"],
                               highlightthickness=1, highlightbackground=c["border"], state="disabled")
        self.log_box.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        for tag, key in (("info", "text_dim"), ("success", "success"),
                         ("warn", "warn"), ("error", "error")):
            self.log_box.tag_configure(tag, foreground=c[key])
        if not self.cfg.show_log:
            self.log_box.grid_remove()

    # ---------------------------------------------------------- 状态栏
    def _build_status(self) -> None:
        c = self.colors
        bar = ttk.Frame(self, style="Panel.TFrame", padding=(12, 5))
        bar.grid(row=4, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self.lbl_status = ttk.Label(bar, text="就绪", style="Status.TLabel")
        self.lbl_status.grid(row=0, column=0, sticky="w")
        self.lbl_env = ttk.Label(bar, text="正在检测运行环境…", style="Status.TLabel")
        self.lbl_env.grid(row=0, column=1, sticky="e")

    # ================================================================ 事件
    def _post_event(self, kind: str, payload: dict) -> None:
        self.events.put((kind, payload))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        except Exception:
            pass
        self._check_clipboard()
        self.after(120, self._pump)

    def _check_clipboard(self) -> None:
        """监听剪贴板：开启后自动把复制到的视频链接加入任务。"""
        if not getattr(self.cfg, "clipboard_watch", False):
            return
        now = time.time()
        if now - self._last_clip_check < 1.2:
            return
        self._last_clip_check = now
        try:
            data = self.clipboard_get()
        except Exception:
            return
        if not data or data == self._last_clip:
            return
        self._last_clip = data
        urls = extract_urls(data)
        if urls:
            self.manager.add_urls(urls, auto_parse=self.cfg.auto_parse)
            self.lbl_status.configure(text=f"已从剪贴板识别 {len(urls)} 个链接")

    def _handle_event(self, kind: str, payload: dict) -> None:
        if kind == "task_added":
            self._add_row(payload["task"])
        elif kind == "task_update":
            self._update_row(payload["task"])
        elif kind == "task_progress":
            self._update_row(payload["task"], progress_only=True)
        elif kind == "task_removed":
            item = self.rows.pop(payload["id"], None)
            if item and self.tree.exists(item):
                self.tree.delete(item)
            self._update_count()
        elif kind == "log":
            self._append_log(payload["message"], payload.get("level", "info"))
        elif kind == "env":
            self.lbl_env.configure(text=payload.get("message", ""))

    # ---------------------------------------------------------- 行操作
    def _add_row(self, task: DownloadTask) -> None:
        row = task.to_row()
        item = self.tree.insert("", "end", values=(row["id"], row["platform"], row["title"],
                                                   row["progress"], row["speed"], row["size"],
                                                   row["eta"], row["state"]))
        self.rows[task.id] = item
        self._update_count()
        self.tree.see(item)

    def _update_row(self, task: DownloadTask, progress_only: bool = False) -> None:
        item = self.rows.get(task.id)
        if item is None or not self.tree.exists(item):
            self._add_row(task)
            return
        row = task.to_row()
        self.tree.item(item, values=(row["id"], row["platform"], row["title"], row["progress"],
                                     row["speed"], row["size"], row["eta"], row["state"]))
        tags = []
        if task.state == TaskState.DONE:
            tags = ["done"]
        elif task.state == TaskState.ERROR:
            tags = ["error"]
        elif task.state == TaskState.PAUSED:
            tags = ["paused"]
        elif task.state.is_active:
            tags = ["active"]
        self.tree.item(item, tags=tags)

    def _update_count(self) -> None:
        self.lbl_count.configure(text=f"共 {len(self.rows)} 个任务")

    def _selected_tasks(self) -> list[DownloadTask]:
        out = []
        for item in self.tree.selection():
            vals = self.tree.item(item, "values")
            if vals:
                task = self.manager.get(int(vals[0]))
                if task:
                    out.append(task)
        return out

    def _row_action(self, action: str) -> None:
        tasks = self._selected_tasks()
        if not tasks:
            return
        for task in tasks:
            if action == "open_file":
                if task.filepath and Path(task.filepath).exists():
                    os.startfile(task.filepath)  # type: ignore[attr-defined]
                else:
                    messagebox.showinfo("提示", "该任务还没有生成文件")
            elif action == "open_dir":
                target = task.filepath or self.cfg.download_dir
                open_folder(Path(target).parent if task.filepath else target)
            elif action == "retry":
                self.manager.retry(task.id)
            elif action == "cancel":
                self.manager.cancel(task.id)
            elif action == "copy_url":
                self._copy(task.url)
            elif action == "copy_title":
                self._copy(task.display_title)
            elif action == "remove":
                self.manager.remove(task.id)

    def _on_row_double_click(self, event) -> None:
        tasks = self._selected_tasks()
        if tasks:
            task = tasks[0]
            if task.state == TaskState.DONE and task.filepath and Path(task.filepath).exists():
                os.startfile(task.filepath)  # type: ignore[attr-defined]
            elif task.state == TaskState.ERROR:
                self.manager.retry(task.id)
            else:
                open_folder(self.cfg.download_dir)

    def _on_row_menu(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            if item not in self.tree.selection():
                self.tree.selection_set(item)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_status.configure(text="已复制到剪贴板")

    def _update_buttons(self) -> None:
        pass

    # ================================================================ 动作
    def _paste(self) -> None:
        try:
            data = self.clipboard_get()
        except Exception:
            data = ""
        if data:
            self.txt_urls.insert("end", ("\n" if self.txt_urls.get("1.0", "end").strip() else "") + data.strip())
        self._on_parse()

    def _on_parse(self) -> None:
        text = self.txt_urls.get("1.0", "end")
        urls = extract_urls(text)
        if not urls:
            self.lbl_status.configure(text="未识别到有效链接")
            return
        self.txt_urls.delete("1.0", "end")
        self.manager.add_urls(urls, auto_parse=True)
        self.lbl_status.configure(text=f"已提交 {len(urls)} 个链接进行解析")

    def _on_download(self) -> None:
        text = self.txt_urls.get("1.0", "end").strip()
        urls = extract_urls(text)
        if urls:
            self.txt_urls.delete("1.0", "end")
            added = self.manager.add_urls(urls, auto_parse=False)
            for t in added:
                self.manager.enqueue(t.id, "download")
            self.lbl_status.configure(text=f"开始下载 {len(added)} 个新任务")
            return
        pending = [t for t in self.manager.tasks
                   if t.state in (TaskState.READY, TaskState.PENDING, TaskState.PAUSED, TaskState.ERROR)]
        if not pending:
            self.lbl_status.configure(text="没有可下载的任务，请先添加链接")
            return
        for t in pending:
            if t.state == TaskState.ERROR or t.info is None:
                self.manager.enqueue(t.id, "parse")
            else:
                self.manager.enqueue(t.id, "download")
        self.lbl_status.configure(text=f"开始下载 {len(pending)} 个任务")

    def _cancel_all(self) -> None:
        for t in list(self.manager.tasks):
            if t.state.is_active or t.state in (TaskState.READY, TaskState.PENDING):
                self.manager.cancel(t.id)

    def _retry_all(self) -> None:
        for t in list(self.manager.tasks):
            if t.state in (TaskState.ERROR, TaskState.CANCELED, TaskState.PAUSED):
                self.manager.retry(t.id)

    def _clear_finished(self) -> None:
        self.manager.clear_finished()

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory(title="选择保存目录", initialdir=self.cfg.download_dir or str(Path.home()))
        if d:
            self.var_dir.set(d)
            self._apply_dir()

    def _apply_dir(self) -> None:
        self.cfg.download_dir = self.var_dir.get().strip() or self.cfg.download_dir
        Path(self.cfg.download_dir).mkdir(parents=True, exist_ok=True)
        ConfigStore.save()

    def _apply_proxy(self) -> None:
        self.cfg.proxy = self.var_proxy.get().strip()
        ConfigStore.save()
        self.lbl_status.configure(text="代理设置已保存")

    def _apply_concurrency(self) -> None:
        try:
            self.cfg.concurrency = max(1, int(self.var_conc.get()))
        except Exception:
            self.cfg.concurrency = 2
        self.manager.set_concurrency(self.cfg.concurrency)
        ConfigStore.save()

    def _on_quality_change(self, _event=None) -> None:
        label = self.var_quality.get()
        for key, lbl, _ in QUALITY_PRESETS:
            if lbl == label:
                self.cfg.quality = key
                self.cfg.audio_only = key == "audio"
                self.var_audio.set(self.cfg.audio_only)
                break
        ConfigStore.save()

    def _on_audio_toggle(self) -> None:
        self.cfg.audio_only = bool(self.var_audio.get())
        if self.cfg.audio_only:
            self.cfg.quality = "audio"
            self.var_quality.set(QUALITY_LABELS["audio"])
        ConfigStore.save()

    def _toggle_log(self) -> None:
        self.cfg.show_log = bool(self.var_show_log.get())
        if self.cfg.show_log:
            self.log_box.grid()
        else:
            self.log_box.grid_remove()
        ConfigStore.save()

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _append_log(self, message: str, level: str = "info") -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {message}\n", level)
        if float(self.log_box.index("end-1c").split(".")[0]) > 500:
            self.log_box.delete("1.0", "150.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        if not self.cfg.show_log:
            self.lbl_status.configure(text=message[:110])

    # ================================================================ 环境
    def _startup_check(self) -> None:
        def run() -> None:
            st = bootstrap.Bootstrap(log=lambda m: self._post_event("log", {"message": m}),
                                     progress=self._env_progress).status()
            if st["ytdlp"]:
                msg = f"yt-dlp {st['ytdlp_version']} ✔   ffmpeg {'✔' if st['ffmpeg'] else '✘（高清合并需要）'}"
                self._post_event("env", {"message": msg})
                self._post_event("log", {"message": f"运行环境就绪：{msg}", "level": "success"})
                self._maybe_auto_update()
            else:
                self._post_event("env", {"message": "未安装 yt-dlp ✘"})
                self._post_event("log", {"message": "首次使用：正在自动下载 yt-dlp / ffmpeg…", "level": "warn"})
                self._install_env()
        threading.Thread(target=run, daemon=True).start()

    def _maybe_auto_update(self) -> None:
        """每天最多自动检查更新一次 yt-dlp（可在设置中关闭）。"""
        if not self.cfg.keep_ytdlp_updated:
            return
        today = time.strftime("%Y-%m-%d")
        if self.cfg.last_update_check == today:
            return
        self.cfg.last_update_check = today
        ConfigStore.save()
        self._post_event("log", {"message": "正在检查 yt-dlp 更新…"})
        if bootstrap.update_ytdlp(log=lambda m: self._post_event("log", {"message": m}),
                                  proxy=self.cfg.proxy, insecure=self.cfg.insecure):
            st = bootstrap.Bootstrap().status()
            self._post_event("env", {"message": f"yt-dlp {st['ytdlp_version']} ✔   "
                                               f"ffmpeg {'✔' if st['ffmpeg'] else '✘'}"})

    def _install_env(self) -> None:
        def run() -> None:
            b = bootstrap.Bootstrap(log=lambda m: self._post_event("log", {"message": m}),
                                    progress=self._env_progress,
                                    proxy=self.cfg.proxy, insecure=self.cfg.insecure)
            ok_dl = bootstrap.install_ytdlp(log=lambda m: self._post_event("log", {"message": m}),
                                            progress=self._env_progress,
                                            proxy=self.cfg.proxy, insecure=self.cfg.insecure)
            ok_ff = bootstrap.install_ffmpeg(log=lambda m: self._post_event("log", {"message": m}),
                                             progress=self._env_progress,
                                             proxy=self.cfg.proxy, insecure=self.cfg.insecure)
            st = b.status()
            msg = f"yt-dlp {st['ytdlp_version'] or '✘'}   ffmpeg {'✔' if st['ffmpeg'] else '✘'}"
            self._post_event("env", {"message": msg})
            self._post_event("log", {
                "message": f"环境安装完成：yt-dlp {'成功' if ok_dl else '失败'}，ffmpeg {'成功' if ok_ff else '失败'}",
                "level": "success" if (ok_dl and ok_ff) else "warn"})
        threading.Thread(target=run, daemon=True).start()

    def _env_progress(self, desc: str, done: int, total: int) -> None:
        from ..utils import human_bytes

        if total:
            self._post_event("env", {"message": f"下载中 {human_bytes(done)} / {human_bytes(total)}"
                                              f"（{done * 100 // max(1, total)}%）"})
        else:
            self._post_event("env", {"message": f"下载中 {human_bytes(done)}"})

    def _open_env_dialog(self) -> None:
        from .env_dialog import EnvDialog

        EnvDialog(self)

    def _open_settings(self) -> None:
        SettingsDialog(self, on_saved=self._on_settings_saved)

    def _on_settings_saved(self) -> None:
        self.cfg = ConfigStore.get()
        apply_theme(self, self.cfg.theme)
        self.var_quality.set(QUALITY_LABELS.get(self.cfg.quality, "最佳画质（自动）"))
        self.var_audio.set(self.cfg.audio_only)
        self.var_dir.set(self.cfg.download_dir)
        self.var_proxy.set(self.cfg.proxy)
        self.var_conc.set(self.cfg.concurrency)
        self.manager.set_concurrency(self.cfg.concurrency)
        self.lbl_status.configure(text="设置已保存")

    # ================================================================ 收尾
    def _on_close(self) -> None:
        try:
            self.cfg.window_geometry = self.winfo_geometry()
            ConfigStore.save()
        except Exception:
            pass
        try:
            self.manager.shutdown()
        except Exception:
            pass
        self.destroy()
