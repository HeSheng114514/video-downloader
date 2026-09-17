# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""运行环境对话框：查看 / 一键安装 / 更新 yt-dlp 与 ffmpeg。"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .. import bootstrap, paths
from ..config import ConfigStore
from ..utils import human_bytes


class EnvDialog(tk.Toplevel):
    def __init__(self, master) -> None:
        super().__init__(master)
        self.cfg = ConfigStore.get()
        self.title("运行环境")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        pad = ttk.Frame(self, padding=16)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="下载引擎依赖", style="Bold.TLabel").pack(anchor="w")
        ttk.Label(pad, text="yt-dlp 负责绝大多数站点；ffmpeg 负责高清音视频合并与音频提取。",
                  style="Dim.TLabel", wraplength=460, justify="left").pack(anchor="w", pady=(2, 10))

        grid = ttk.Frame(pad)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="yt-dlp").grid(row=0, column=0, sticky="w", pady=4)
        self.lbl_ytdlp = ttk.Label(grid, text="检测中…")
        self.lbl_ytdlp.grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="ffmpeg").grid(row=1, column=0, sticky="w", pady=4)
        self.lbl_ffmpeg = ttk.Label(grid, text="检测中…")
        self.lbl_ffmpeg.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(grid, text="安装目录").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Label(grid, text=str(paths.bin_dir()), style="Dim.TLabel").grid(row=2, column=1, sticky="w", pady=4)

        self.pb = ttk.Progressbar(pad, mode="determinate", maximum=100)
        self.pb.pack(fill="x", pady=(12, 4))
        self.lbl_progress = ttk.Label(pad, text="", style="Dim.TLabel")
        self.lbl_progress.pack(anchor="w")

        self.log_box = tk.Text(pad, height=8, wrap="word", relief="flat", font=("Consolas", 9),
                               bg="#ffffff", fg="#4b5563", highlightthickness=1,
                               highlightbackground="#e5e7eb", state="disabled")
        self.log_box.pack(fill="both", expand=True, pady=(8, 10))

        bar = ttk.Frame(pad)
        bar.pack(fill="x")
        ttk.Button(bar, text="关闭", command=self.destroy).pack(side="right")
        self.btn_update = ttk.Button(bar, text="更新 yt-dlp", command=self._update)
        self.btn_update.pack(side="right", padx=6)
        self.btn_install = ttk.Button(bar, text="一键安装 / 修复", style="Accent.TButton", command=self._install)
        self.btn_install.pack(side="right", padx=6)
        ttk.Button(bar, text="重新检测", command=self._refresh).pack(side="left")

        self._refresh()

    # ------------------------------------------------------------
    def _log(self, msg: str) -> None:
        self.after(0, self._log_ui, msg)

    def _log_ui(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _progress(self, title: str, done: int, total: int) -> None:
        def ui() -> None:
            if total:
                pct = min(100, done * 100 // max(1, total))
                self.pb.configure(value=pct)
                self.lbl_progress.configure(text=f"下载中 {human_bytes(done)} / {human_bytes(total)}（{pct}%）")
            else:
                self.lbl_progress.configure(text=f"下载中 {human_bytes(done)}")
        self.after(0, ui)

    def _refresh(self) -> None:
        cmd = bootstrap.ytdlp_command()
        ver = bootstrap.ytdlp_version(cmd) if cmd else ""
        self.lbl_ytdlp.configure(
            text=(f"✔ {ver}" if ver else "✘ 未安装") + ("" if cmd else ""),
        )
        ff = paths.find_ffmpeg()
        self.lbl_ffmpeg.configure(text=f"✔ {ff}" if ff else "✘ 未安装（高清合并/音频提取需要）")

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_install.configure(state=state)
        self.btn_update.configure(state=state)

    # ------------------------------------------------------------
    def _install(self) -> None:
        self._busy(True)

        def run() -> None:
            try:
                ok1 = bootstrap.install_ytdlp(self._log, self._progress, self.cfg.proxy, self.cfg.insecure)
                ok2 = bootstrap.install_ffmpeg(self._log, self._progress, self.cfg.proxy, self.cfg.insecure)
                self._log("安装结束：" + f"yt-dlp {'成功' if ok1 else '失败'}，ffmpeg {'成功' if ok2 else '失败'}")
                if not (ok1 and ok2):
                    self._log("提示：可手动把 yt-dlp.exe 与 ffmpeg.exe 放入 bin 目录")
            finally:
                self.after(0, self._refresh)
                self.after(0, lambda: self._busy(False))
                self.after(0, lambda: self.pb.configure(value=0))

        threading.Thread(target=run, daemon=True).start()

    def _update(self) -> None:
        self._busy(True)

        def run() -> None:
            try:
                bootstrap.update_ytdlp(self._log, self._progress, self.cfg.proxy, self.cfg.insecure)
            finally:
                self.after(0, self._refresh)
                self.after(0, lambda: self._busy(False))

        threading.Thread(target=run, daemon=True).start()
