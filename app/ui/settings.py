# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""设置对话框。"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .. import bootstrap, paths
from ..config import BROWSERS, QUALITY_LABELS, QUALITY_PRESETS, Config, ConfigStore
from .theme import FONT_FAMILY, palette


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, on_saved: Callable[[], None] | None = None) -> None:
        super().__init__(master)
        self.cfg = ConfigStore.get()
        self.on_saved = on_saved
        c = palette(self.cfg.theme)
        self.colors = c
        self.title("设置")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)
        self.configure(bg=c["bg"])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 6))

        self._vars: dict[str, tk.Variable] = {}
        self._tab_download(nb)
        self._tab_network(nb)
        self._tab_advanced(nb)

        bar = ttk.Frame(self, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text="恢复默认", command=self._reset).pack(side="left")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="保存", style="Accent.TButton", command=self._save).pack(side="right")

        self.update_idletasks()
        try:
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + 80
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    # ------------------------------------------------------------ 控件助手
    def _v(self, key: str, value) -> tk.Variable:
        var = tk.BooleanVar(value=value) if isinstance(value, bool) else tk.StringVar(value=str(value))
        self._vars[key] = var
        return var

    def _page(self, nb: ttk.Notebook, title: str) -> ttk.Frame:
        frame = ttk.Frame(nb, padding=16)
        nb.add(frame, text=title)
        frame.columnconfigure(1, weight=1)
        return frame

    def _row(self, parent: ttk.Frame, r: int, label: str, widget: tk.Widget | None = None) -> int:
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=6, padx=(0, 12))
        if widget is not None:
            widget.grid(row=r, column=1, sticky="ew", pady=6)
        return r + 1

    # ------------------------------------------------------------ 各页
    def _tab_download(self, nb: ttk.Notebook) -> None:
        f = self._page(nb, "下载")
        r = 0

        box = ttk.Frame(f)
        ent = ttk.Entry(box, textvariable=self._v("download_dir", self.cfg.download_dir))
        ent.pack(side="left", fill="x", expand=True)
        ttk.Button(box, text="浏览…", command=lambda: self._pick_dir(ent)).pack(side="left", padx=(6, 0))
        r = self._row(f, r, "保存目录", box)

        r = self._row(f, r, "文件名模板",
                      ttk.Entry(f, textvariable=self._v("filename_template", self.cfg.filename_template)))
        ttk.Label(f, text="可用变量：%(title)s %(id)s %(uploader)s %(ext)s %(upload_date)s",
                  style="Dim.TLabel").grid(row=r, column=1, sticky="w")
        r += 1

        r = self._row(f, r, "默认画质",
                      ttk.Combobox(f, state="readonly", textvariable=self._v("quality", self.cfg.quality),
                                   values=[k for k, _, _ in QUALITY_PRESETS], width=18))
        ttk.Label(f, text="best=最高可用 / 1080=≤1080P / audio=仅音频", style="Dim.TLabel").grid(
            row=r, column=1, sticky="w")
        r += 1

        r = self._row(f, r, "音频格式",
                      ttk.Combobox(f, state="readonly", textvariable=self._v("audio_format", self.cfg.audio_format),
                                   values=["mp3", "m4a", "flac", "wav", "opus"], width=18))

        r = self._row(f, r, "合集下载项",
                      ttk.Entry(f, textvariable=self._v("playlist_items", self.cfg.playlist_items)))
        ttk.Label(f, text="留空=全部，可填 1-10 或 1,3,5", style="Dim.TLabel").grid(row=r, column=1, sticky="w")
        r += 1

        opts = ttk.Frame(f)
        ttk.Checkbutton(opts, text="仅下载音频", variable=self._v("audio_only", self.cfg.audio_only)).pack(anchor="w")
        ttk.Checkbutton(opts, text="按平台建立子文件夹", variable=self._v("subdir_per_platform", self.cfg.subdir_per_platform)).pack(anchor="w")
        ttk.Checkbutton(opts, text="允许下载整个合集/播放列表", variable=self._v("playlist", self.cfg.playlist)).pack(anchor="w")
        ttk.Checkbutton(opts, text="合并/转封装为 MP4", variable=self._v("prefer_mp4", self.cfg.prefer_mp4)).pack(anchor="w")
        ttk.Checkbutton(opts, text="同名文件自动加序号（不覆盖）", variable=self._v("keep_original", self.cfg.keep_original)).pack(anchor="w")
        ttk.Checkbutton(opts, text="保存封面图片", variable=self._v("write_thumbnail", self.cfg.write_thumbnail)).pack(anchor="w")
        ttk.Checkbutton(opts, text="嵌入封面", variable=self._v("embed_thumbnail", self.cfg.embed_thumbnail)).pack(anchor="w")
        ttk.Checkbutton(opts, text="嵌入元数据", variable=self._v("embed_metadata", self.cfg.embed_metadata)).pack(anchor="w")
        ttk.Checkbutton(opts, text="下载字幕", variable=self._v("write_subtitles", self.cfg.write_subtitles)).pack(anchor="w")
        ttk.Checkbutton(opts, text="下载自动字幕", variable=self._v("auto_subtitle", self.cfg.auto_subtitle)).pack(anchor="w")
        ttk.Checkbutton(opts, text="移除赞助片段（SponsorBlock）", variable=self._v("sponsorblock", self.cfg.sponsorblock)).pack(anchor="w")
        self._row(f, r, "其他选项", opts)

    def _tab_network(self, nb: ttk.Notebook) -> None:
        f = self._page(nb, "网络与登录")
        r = 0

        r = self._row(f, r, "代理服务器",
                      ttk.Entry(f, textvariable=self._v("proxy", self.cfg.proxy)))
        ttk.Label(f, text="支持 http:// https:// socks5://，如 http://127.0.0.1:7890",
                  style="Dim.TLabel").grid(row=r, column=1, sticky="w")
        r += 1

        browser_box = ttk.Frame(f)
        self.cmb_browser = ttk.Combobox(browser_box, state="readonly",
                                        textvariable=self._v("cookies_from_browser", self.cfg.cookies_from_browser),
                                        values=BROWSERS, width=16)
        self.cmb_browser.pack(side="left")
        self.cmb_browser.bind("<<ComboboxSelected>>", lambda e: self._check_browser())
        ttk.Button(browser_box, text="🍪 Cookie 助手", command=self._open_cookie_dialog).pack(side="left", padx=(8, 0))
        ttk.Button(browser_box, text="✍ 手动填写 Cookie", command=self._open_manual_cookie).pack(side="left", padx=(6, 0))
        r = self._row(f, r, "Cookie 来源", browser_box)
        self.lbl_browser_hint = ttk.Label(f, text="", style="Dim.TLabel", wraplength=440, justify="left")
        self.lbl_browser_hint.grid(row=r, column=1, sticky="w")
        r += 1

        cbox = ttk.Frame(f)
        cfile = ttk.Entry(cbox, textvariable=self._v("cookies_file", self.cfg.cookies_file))
        cfile.pack(side="left", fill="x", expand=True)
        ttk.Button(cbox, text="选择…", command=lambda: self._pick_file(cfile)).pack(side="left", padx=(6, 0))
        r = self._row(f, r, "cookies.txt 文件", cbox)
        ttk.Label(f, text="优先级：cookies.txt > 浏览器 Cookie",
                  style="Dim.TLabel").grid(row=r, column=1, sticky="w")
        r += 1

        r = self._row(f, r, "自定义 User-Agent",
                      ttk.Entry(f, textvariable=self._v("user_agent", self.cfg.user_agent)))
        r = self._row(f, r, "", ttk.Checkbutton(f, text="忽略 SSL 证书错误（不推荐）",
                                                variable=self._v("insecure", self.cfg.insecure)))

        tips = ("提示：抖音、快手、B站高清、YouTube 会员内容都需要登录 Cookie。\n"
                "三种来源任选其一：① ✍ 手动粘贴（最直接，推荐）② cookies.txt 文件 ③ 浏览器读取。\n"
                "⚠ Windows 上 Chrome / Edge 自 127 版起启用 App-Bound 加密，"
                "yt-dlp 无法解密其 Cookie（官方已知限制）—— 请勿选 chrome / edge，"
                "用「🍪 Cookie 助手」或「✍ 手动填写 Cookie」。")
        ttk.Label(f, text=tips, style="Dim.TLabel", wraplength=470, justify="left").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self._check_browser()

    def _tab_advanced(self, nb: ttk.Notebook) -> None:
        f = self._page(nb, "高级")
        r = 0
        r = self._row(f, r, "同时下载数", ttk.Spinbox(f, from_=1, to=10, width=8,
                                                   textvariable=self._v("concurrency", self.cfg.concurrency)))
        r = self._row(f, r, "单任务分片并发", ttk.Spinbox(f, from_=1, to=16, width=8,
                                                    textvariable=self._v("concurrent_fragments", self.cfg.concurrent_fragments)))
        r = self._row(f, r, "重试次数", ttk.Spinbox(f, from_=0, to=30, width=8,
                                                 textvariable=self._v("retries", self.cfg.retries)))
        r = self._row(f, r, "限速", ttk.Entry(f, textvariable=self._v("speed_limit", self.cfg.speed_limit)))
        ttk.Label(f, text="留空=不限速，如 5M / 500K", style="Dim.TLabel").grid(row=r, column=1, sticky="w")
        r += 1
        r = self._row(f, r, "界面主题",
                      ttk.Combobox(f, state="readonly", values=["light", "dark"], width=18,
                                   textvariable=self._v("theme", self.cfg.theme)))
        r = self._row(f, r, "额外 yt-dlp 参数",
                      ttk.Entry(f, textvariable=self._v("extra_ytdlp_args", self.cfg.extra_ytdlp_args)))
        r = self._row(f, r, "", ttk.Checkbutton(f, text="显示日志面板",
                                                variable=self._v("show_log", self.cfg.show_log)))
        r = self._row(f, r, "", ttk.Checkbutton(f, text="添加链接后自动解析",
                                                variable=self._v("auto_parse", self.cfg.auto_parse)))
        r = self._row(f, r, "", ttk.Checkbutton(f, text="监听剪贴板，复制链接即自动添加",
                                                variable=self._v("clipboard_watch", self.cfg.clipboard_watch)))
        r = self._row(f, r, "", ttk.Checkbutton(f, text="启动时自动更新 yt-dlp",
                                                variable=self._v("keep_ytdlp_updated", self.cfg.keep_ytdlp_updated)))
        return

    # ------------------------------------------------------------ 动作
    def _check_browser(self) -> None:
        """选择 Chromium 系浏览器时给出 App-Bound 加密警告。"""
        from .. import cookies as ck

        if not hasattr(self, "lbl_browser_hint"):
            return
        manual = getattr(self.cfg, "manual_cookies", None) or {}
        b = str(self._vars.get("cookies_from_browser").get() if "cookies_from_browser" in self._vars else "").strip()
        if manual:
            self.lbl_browser_hint.configure(
                text=f"✔ 已使用手动填写的 Cookie（{ck.manual_cookie_summary(manual)}），"
                     f"优先级高于浏览器读取，不会触发 App-Bound 问题",
                foreground=self.colors.get("success"))
        elif not b:
            self.lbl_browser_hint.configure(
                text="抖音、B站高清、YouTube 会员等需要登录态时使用（浏览器须已登录）",
                foreground=self.colors.get("text_dim"))
        elif b in ck.CHROMIUM_BROWSERS and ck.appbound_risk()[0]:
            self.lbl_browser_hint.configure(
                text="⚠ 该浏览器受 App-Bound 加密限制，Cookie 无法被读取，"
                     "下载会报「Failed to decrypt with DPAPI」。请改用 Firefox、cookies.txt，"
                     "或点「✍ 手动填写 Cookie」。",
                foreground=self.colors.get("error"))
        elif b == "firefox":
            profs = [p for p in ck.find_firefox_profiles() if p["exists"]]
            self.lbl_browser_hint.configure(
                text=("✔ Firefox 可正常读取 Cookie（" + "、".join(p["name"] for p in profs) + "）"
                      if profs else "⚠ 未检测到 Firefox 配置文件，请先在 Firefox 中登录目标网站"),
                foreground=self.colors.get("success") if profs else self.colors.get("warn"))
        else:
            self.lbl_browser_hint.configure(text="", foreground=self.colors.get("text_dim"))

    def _open_manual_cookie(self) -> None:
        from .manual_cookie_dialog import ManualCookieDialog

        try:
            self.grab_release()
        except Exception:
            pass
        dlg = ManualCookieDialog(self, on_saved=self._check_browser)
        self.wait_window(dlg)
        try:
            self.grab_set()
        except Exception:
            pass
        self._check_browser()

    def _open_cookie_dialog(self) -> None:
        from .cookie_dialog import CookieDialog

        plats: list[str] = []
        master = self.master
        try:
            for t in getattr(getattr(master, "manager", None), "tasks", []):
                if t.platform not in plats:
                    plats.append(t.platform)
        except Exception:
            pass
        # 模态叠模态：先释放本窗口的 grab，关闭子窗口后再取回
        try:
            self.grab_release()
        except Exception:
            pass
        dlg = CookieDialog(self, platforms=plats or ["bilibili", "douyin", "kuaishou"])
        self.wait_window(dlg)
        try:
            self.grab_set()
        except Exception:
            pass
        if hasattr(self, "lbl_browser_hint"):
            self._check_browser()

    def _pick_dir(self, ent: ttk.Entry) -> None:
        d = filedialog.askdirectory(parent=self, initialdir=ent.get() or str(Path.home()))
        if d:
            ent.delete(0, "end")
            ent.insert(0, d)

    def _pick_file(self, ent: ttk.Entry) -> None:
        f = filedialog.askopenfilename(parent=self, title="选择 cookies.txt",
                                       filetypes=[("Cookies", "*.txt"), ("所有文件", "*.*")])
        if f:
            ent.delete(0, "end")
            ent.insert(0, f)

    def _reset(self) -> None:
        if not messagebox.askyesno("恢复默认", "确定要恢复所有默认设置吗？", parent=self):
            return
        default = Config()
        for key, var in self._vars.items():
            val = getattr(default, key, None)
            if isinstance(var, tk.BooleanVar):
                var.set(bool(val))
            else:
                var.set("" if val is None else str(val))

    def _save(self) -> None:
        cfg: Config = self.cfg
        for key, var in self._vars.items():
            if not hasattr(cfg, key):
                continue
            val = var.get()
            current = getattr(cfg, key)
            try:
                if isinstance(current, bool):
                    setattr(cfg, key, bool(val))
                elif isinstance(current, int):
                    setattr(cfg, key, int(val))
                else:
                    setattr(cfg, key, str(val).strip())
            except Exception:
                pass
        if not cfg.download_dir:
            cfg.download_dir = str(paths.default_download_dir())
        Path(cfg.download_dir).mkdir(parents=True, exist_ok=True)
        ConfigStore.save()
        if self.on_saved:
            self.on_saved()
        self.destroy()
