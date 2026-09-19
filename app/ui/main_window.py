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
from .theme import (FONT_FAMILY, MONO_FAMILY, apply_theme, make_card,
                    make_divider, make_text)

APP_TITLE = f"视频下载器 v{paths.APP_VERSION}"


class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = ConfigStore.get()
        self.events: queue.Queue = queue.Queue()
        self.rows: dict[int, str] = {}
        self.colors = apply_theme(self, self.cfg.theme)
        self._applied_theme = self.cfg.theme
        self.manager = TaskManager(self._post_event, self.cfg)

        self.title(APP_TITLE)
        geometry = self.cfg.window_geometry or "1240x820"
        self.geometry(geometry)
        self.minsize(1040, 680)
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
        bar = ttk.Frame(self, style="Header.TFrame", padding=(18, 11, 14, 11))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        left = ttk.Frame(bar, style="Header.TFrame")
        left.grid(row=0, column=0, sticky="w")
        ttk.Label(left, text="🎬 视频下载器", style="HeaderBrand.TLabel").pack(side="left")
        ttk.Label(left, text=f" v{paths.APP_VERSION} ", style="HeaderChip.TLabel").pack(
            side="left", padx=(9, 0))
        ttk.Label(left, text=SUPPORTED_HINT, style="HeaderHint.TLabel").pack(
            side="left", padx=(11, 0))

        right = ttk.Frame(bar, style="Header.TFrame")
        right.grid(row=0, column=2, sticky="e")
        self.btn_env = ttk.Button(right, text="⚙ 运行环境", style="Tool.TButton",
                                  command=self._open_env_dialog)
        self.btn_env.pack(side="right")
        self.btn_theme = ttk.Button(right, text=self._theme_icon(), style="Tool.TButton",
                                    command=self._toggle_theme)
        self.btn_theme.pack(side="right", padx=(0, 2))
        ttk.Button(right, text="🛠 设置", style="Tool.TButton",
                   command=self._open_settings).pack(side="right", padx=(0, 2))

        tk.Frame(self, height=2, bg=c["accent"], bd=0,
                 highlightthickness=0).grid(row=0, column=0, sticky="sew")

    def _theme_icon(self) -> str:
        return "☀ 浅色" if self.cfg.theme == "dark" else "🌙 深色"

    def _toggle_theme(self) -> None:
        self.cfg.theme = "light" if self.cfg.theme == "dark" else "dark"
        ConfigStore.save()
        self._on_settings_saved()

    def _rebuild_ui(self) -> None:
        """按当前主题重建界面（保留输入框内容、任务列表与日志）。

        卡片与文本框是 classic tk 控件，仅改 ttk 样式无法让它们换色，
        因此换主题时整体重建一次。
        """
        text = ""
        log = ""
        try:
            text = self.txt_urls.get("1.0", "end").rstrip("\n")
        except Exception:
            pass
        try:
            log = self.log_box.get("1.0", "end").rstrip("\n")
        except Exception:
            pass

        for child in list(self.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        self.rows.clear()

        self.colors = apply_theme(self, self.cfg.theme)
        self._applied_theme = self.cfg.theme
        self._build_ui()

        if text:
            self.txt_urls.insert("1.0", text)
        for task in self.manager.tasks:
            self._add_row(task)
            self._update_row(task)
        self._update_count()
        if log:
            self.log_box.configure(state="normal")
            self.log_box.insert("1.0", log + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self._refresh_env_dot()

    # ---------------------------------------------------------- 输入区
    def _build_input(self) -> None:
        c = self.colors
        wrap = ttk.Frame(self, style="Canvas.TFrame", padding=(16, 14, 16, 7))
        wrap.grid(row=1, column=0, sticky="ew")
        wrap.columnconfigure(0, weight=3, minsize=420)
        wrap.columnconfigure(1, weight=2, minsize=300)

        # ---------- 左：链接输入卡片 ----------
        card = make_card(wrap, c)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(11, 0))
        ttk.Label(head, text="视频链接", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(head, text="每行一个，可直接粘贴整段分享文案",
                  style="CardHint.TLabel").pack(side="left", padx=(9, 0))
        ttk.Label(head, text="Ctrl+Enter 解析", style="CardHint.TLabel").pack(side="right")

        box = ttk.Frame(card, style="Card.TFrame")
        box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(9, 0))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        self.txt_urls = make_text(box, c, mono=True, height=4, wrap="none")
        self.txt_urls.grid(row=0, column=0, sticky="nsew")
        self.txt_urls.bind("<Control-Return>", lambda e: self._on_parse())
        sb = ttk.Scrollbar(box, orient="vertical", command=self.txt_urls.yview)
        sb.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.txt_urls.configure(yscrollcommand=sb.set)

        btns = ttk.Frame(card, style="Card.TFrame")
        btns.grid(row=2, column=0, sticky="ew", padx=14, pady=(10, 12))
        ttk.Button(btns, text="📋 粘贴", style="Secondary.TButton",
                   command=self._paste).pack(side="left")
        ttk.Button(btns, text="🗑 清空", style="Secondary.TButton",
                   command=lambda: self.txt_urls.delete("1.0", "end")).pack(side="left", padx=6)
        ttk.Button(btns, text="🔍 解析", style="Secondary.TButton",
                   command=self._on_parse).pack(side="left")
        ttk.Button(btns, text="⬇  开始下载", style="Primary.TButton",
                   command=self._on_download).pack(side="right")

        # ---------- 右：下载选项卡片 ----------
        card2 = make_card(wrap, c)
        card2.grid(row=0, column=1, sticky="nsew")
        card2.columnconfigure(0, weight=1)

        ttk.Label(card2, text="下载选项", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=14, pady=(11, 8))

        body = ttk.Frame(card2, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        body.columnconfigure(0, minsize=54)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="画质", style="CardDim.TLabel").grid(
            row=0, column=0, sticky="w", pady=4)
        self.var_quality = tk.StringVar(value=QUALITY_LABELS.get(self.cfg.quality, "最佳画质（自动）"))
        self.cmb_quality = ttk.Combobox(body, textvariable=self.var_quality, state="readonly",
                                        values=[label for _, label, _ in QUALITY_PRESETS])
        self.cmb_quality.grid(row=0, column=1, sticky="ew", pady=4)
        self.cmb_quality.bind("<<ComboboxSelected>>", self._on_quality_change)

        self.var_audio = tk.BooleanVar(value=self.cfg.audio_only)
        ttk.Checkbutton(body, text="仅音频（提取 MP3）", variable=self.var_audio,
                        style="Card.TCheckbutton", command=self._on_audio_toggle).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 4))

        ttk.Label(body, text="保存到", style="CardDim.TLabel").grid(
            row=2, column=0, sticky="w", pady=4)
        dirbox = ttk.Frame(body, style="Card.TFrame")
        dirbox.grid(row=2, column=1, sticky="ew", pady=4)
        dirbox.columnconfigure(0, weight=1)
        self.var_dir = tk.StringVar(value=self.cfg.download_dir)
        ent = ttk.Entry(dirbox, textvariable=self.var_dir)
        ent.grid(row=0, column=0, sticky="ew")
        ent.bind("<FocusOut>", lambda e: self._apply_dir())
        ent.bind("<Return>", lambda e: self._apply_dir())
        ttk.Button(dirbox, text="浏览", style="Secondary.TButton",
                   command=self._choose_dir).grid(row=0, column=1, padx=(6, 0))

        row = ttk.Frame(body, style="Card.TFrame")
        row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Label(row, text="并发", style="CardDim.TLabel").pack(side="left")
        self.var_conc = tk.IntVar(value=self.cfg.concurrency)
        ttk.Spinbox(row, from_=1, to=10, width=4, textvariable=self.var_conc,
                    command=self._apply_concurrency).pack(side="left", padx=(8, 16))
        ttk.Label(row, text="代理", style="CardDim.TLabel").pack(side="left")
        self.var_proxy = tk.StringVar(value=self.cfg.proxy)
        pe = ttk.Entry(row, textvariable=self.var_proxy)
        pe.pack(side="left", padx=(8, 0), fill="x", expand=True)
        pe.bind("<FocusOut>", lambda e: self._apply_proxy())
        pe.bind("<Return>", lambda e: self._apply_proxy())

        ttk.Label(body, text="YouTube / TikTok 等站点需要代理，如 http://127.0.0.1:7890",
                  style="CardHint.TLabel", wraplength=290, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(7, 0))

    # ---------------------------------------------------------- 任务表
    def _build_tasks(self) -> None:
        c = self.colors
        wrap = ttk.Frame(self, style="Canvas.TFrame", padding=(16, 0, 16, 7))
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        card = make_card(wrap, c)
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(11, 7))
        ttk.Label(head, text="任务列表", style="CardTitle.TLabel").pack(side="left")
        self.lbl_count = ttk.Label(head, text="共 0 个任务", style="CardHint.TLabel")
        self.lbl_count.pack(side="left", padx=(9, 0))

        for text, cmd in (("清空已完成", self._clear_finished),
                          ("全部取消", self._cancel_all),
                          ("全部重试", self._retry_all),
                          ("打开目录", lambda: open_folder(self.cfg.download_dir))):
            ttk.Button(head, text=text, style="Ghost.TButton", command=cmd).pack(
                side="right", padx=3)

        body = ttk.Frame(card, style="Card.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=(14, 8), pady=(0, 12))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        cols = ("id", "platform", "title", "progress", "speed", "size", "eta", "state")
        heads = {"id": "#", "platform": "平台", "title": "标题", "progress": "进度",
                 "speed": "速度", "size": "大小", "eta": "剩余", "state": "状态"}
        widths = {"id": 46, "platform": 74, "title": 340, "progress": 176,
                  "speed": 100, "size": 136, "eta": 74, "state": 156}

        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="extended")
        for col in cols:
            self.tree.heading(col, text=heads[col])
            self.tree.column(col, width=widths[col], minwidth=46,
                             anchor="w" if col == "title" else "center",
                             stretch=(col == "title"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        vs.grid(row=0, column=1, sticky="ns", padx=(2, 0))
        self.tree.configure(yscrollcommand=vs.set)

        # 斑马纹 + 状态着色（状态标签只设前景色，条纹标签只设背景色，互不冲突）
        self.tree.tag_configure("stripe_even", background=c["card"])
        self.tree.tag_configure("stripe_odd", background=c["stripe"])
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
        self.log_wrap = ttk.Frame(self, style="Canvas.TFrame", padding=(16, 0, 16, 9))
        self.log_wrap.grid(row=3, column=0, sticky="ew")
        self.log_wrap.columnconfigure(0, weight=1)

        self.log_card = make_card(self.log_wrap, c)
        self.log_card.grid(row=0, column=0, sticky="ew")
        self.log_card.columnconfigure(0, weight=1)

        head = ttk.Frame(self.log_card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew", padx=14, pady=(9, 0))
        self.var_show_log = tk.BooleanVar(value=self.cfg.show_log)
        ttk.Checkbutton(head, text="运行日志", variable=self.var_show_log,
                        style="Card.TCheckbutton", command=self._toggle_log).pack(side="left")
        ttk.Label(head, text="解析与下载的详细过程", style="CardHint.TLabel").pack(
            side="left", padx=(9, 0))
        ttk.Button(head, text="清空", style="Ghost.TButton",
                   command=lambda: self._clear_log()).pack(side="right")

        self.log_box = make_text(self.log_card, c, mono=True, height=5, wrap="word",
                                 state="disabled", highlightthickness=0, bg=c["card_alt"],
                                 padx=10, pady=7)
        self.log_box.grid(row=1, column=0, sticky="ew", padx=14, pady=(7, 12))
        for tag, key in (("info", "text_dim"), ("success", "success"),
                         ("warn", "warn"), ("error", "error")):
            self.log_box.tag_configure(tag, foreground=c[key])
        if not self.cfg.show_log:
            self.log_card.grid_remove()

    # ---------------------------------------------------------- 状态栏
    def _build_status(self) -> None:
        c = self.colors
        bar = ttk.Frame(self, style="StatusBar.TFrame", padding=(16, 7))
        bar.grid(row=4, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)

        self.lbl_dot = tk.Label(bar, text="●", bg=c["card"], fg=c["success"],
                                font=(FONT_FAMILY, 9), bd=0)
        self.lbl_dot.grid(row=0, column=0, sticky="w")
        self.lbl_status = ttk.Label(bar, text="就绪", style="Status.TLabel")
        self.lbl_status.grid(row=0, column=1, sticky="w", padx=(7, 0))
        self.lbl_env = ttk.Label(bar, text="正在检测运行环境…", style="Status.TLabel")
        self.lbl_env.grid(row=0, column=2, sticky="e")

        tk.Frame(self, height=1, bg=c["border"], bd=0,
                 highlightthickness=0).grid(row=4, column=0, sticky="new")

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
            self._refresh_env_dot()

    def _refresh_env_dot(self) -> None:
        """状态栏的小圆点：绿=就绪，红=缺依赖。"""
        txt = self.lbl_env.cget("text")
        try:
            good = ("✔" in txt) and ("yt-dlp" in txt)
            bad = ("未安装" in txt) or ("✘" in txt)
            color = self.colors["error"] if (bad and not good) else (
                self.colors["success"] if good else self.colors["text_mute"])
            self.lbl_dot.configure(fg=color)
        except Exception:
            pass

    # ---------------------------------------------------------- 行操作
    def _add_row(self, task: DownloadTask) -> None:
        row = task.to_row()
        item = self.tree.insert("", "end", values=(row["id"], row["platform"], row["title"],
                                                   row["progress"], row["speed"], row["size"],
                                                   row["eta"], row["state"]))
        self.rows[task.id] = item
        try:
            stripe = "stripe_odd" if self.tree.index(item) % 2 else "stripe_even"
            self.tree.item(item, tags=[stripe])
        except Exception:
            pass
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
            tags.append("done")
        elif task.state == TaskState.ERROR:
            tags.append("error")
        elif task.state == TaskState.PAUSED:
            tags.append("paused")
        elif task.state.is_active:
            tags.append("active")
        # 斑马纹（只设背景，与状态标签的前景色互不冲突）
        try:
            stripe = "stripe_odd" if self.tree.index(item) % 2 else "stripe_even"
        except Exception:
            stripe = "stripe_even"
        tags.append(stripe)
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
            # 逐条换行插入，避免多条链接粘成一行被当成一个 URL
            urls = extract_urls(data)
            new_text = "\n".join(urls) if urls else data.strip()
            current = self.txt_urls.get("1.0", "end").strip()
            self.txt_urls.insert("end", ("\n" if current else "") + new_text)
        self._on_parse()

    def _on_parse(self) -> None:
        text = self.txt_urls.get("1.0", "end")
        urls = extract_urls(text)
        if not urls:
            self.lbl_status.configure(text="未识别到有效链接")
            return
        added, existing = self.manager.upsert_urls(urls, auto_parse=True)
        overwrite = self.cfg.duplicate_action != "skip"
        refreshed = 0
        if overwrite:
            for t in existing:
                if not t.state.is_active:
                    self.manager.enqueue(t.id, "parse")
                    refreshed += 1
        if not added and not refreshed:
            self.lbl_status.configure(
                text=f"{len(existing)} 个视频已在列表中，已按设置跳过重复（输入框已保留；"
                     f"可在「设置 → 下载」改为「覆盖重新下载」）")
            return
        # 只有确实提交了任务才清空输入框，避免「链接被清空却没任何反应」
        self.txt_urls.delete("1.0", "end")
        parts = []
        if added:
            parts.append(f"新增 {len(added)} 个")
        if refreshed:
            parts.append(f"重新解析 {len(refreshed)} 个（已存在）")
        self.lbl_status.configure(text="解析中：" + "，".join(parts))

    def _on_download(self) -> None:
        text = self.txt_urls.get("1.0", "end").strip()
        urls = extract_urls(text)
        if urls:
            added, existing = self.manager.upsert_urls(urls, auto_parse=False)
            for t in added:
                self.manager.enqueue(t.id, "download")
            overwritten = 0
            skipped = 0
            if self.cfg.duplicate_action == "skip":
                skipped = len(existing)
            else:
                # 已存在的视频按设置「覆盖下载」，而不是静默跳过
                for t in existing:
                    if self.manager.restart(t.id, overwrite=True):
                        overwritten += 1
            started = len(added) + overwritten
            if not started:
                if skipped:
                    self.lbl_status.configure(
                        text=f"{skipped} 个视频已在列表中，已按设置跳过（输入框已保留；"
                             f"如需重新下载请在「设置 → 下载」改为「覆盖重新下载」）")
                else:
                    self.lbl_status.configure(text="这些链接正在下载中，无需重复提交（输入框已保留）")
                return
            self.txt_urls.delete("1.0", "end")
            parts = []
            if len(added):
                parts.append(f"新增下载 {len(added)} 个")
            if overwritten:
                parts.append(f"覆盖重新下载 {overwritten} 个")
            if skipped:
                parts.append(f"跳过重复 {skipped} 个")
            self.lbl_status.configure(text="开始下载：" + "，".join(parts))
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
            self.log_card.grid()
        else:
            self.log_card.grid_remove()
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
        # 换主题需要重建界面（卡片/文本框是 classic tk 控件，改 ttk 样式不会重绘它们）
        if getattr(self, "_applied_theme", self.cfg.theme) != self.cfg.theme:
            self._rebuild_ui()
        else:
            self.colors = apply_theme(self, self.cfg.theme)
            if hasattr(self, "btn_theme"):
                self.btn_theme.configure(text=self._theme_icon())
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
