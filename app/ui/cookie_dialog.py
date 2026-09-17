# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""Cookie 助手：诊断浏览器 Cookie 可用性并给出可执行方案。

主要解决 Windows 上 Chrome / Edge 127+ 的 App-Bound 加密导致
`--cookies-from-browser` 报 "Failed to decrypt with DPAPI" 的问题。
"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import cookies as ck
from ..config import ConfigStore
from ..utils import human_bytes

EXT_URL = ("https://chromewebstore.google.com/detail/"
           "get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc")
ISSUE_URL = "https://github.com/yt-dlp/yt-dlp/issues/10927"


class CookieDialog(tk.Toplevel):
    def __init__(self, master, platforms: list[str] | None = None) -> None:
        super().__init__(master)
        self.cfg = ConfigStore.get()
        self.platforms = platforms or ["bilibili"]
        self.title("Cookie 助手")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        pad = ttk.Frame(self, padding=16)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="浏览器 Cookie 获取助手", style="Bold.TLabel").pack(anchor="w")
        ttk.Label(
            pad,
            text="抖音、快手、B 站高清、YouTube 会员内容都需要登录 Cookie。\n"
                 "Windows 上 Chrome / Edge 自 127 版起启用 App-Bound 加密，"
                 "yt-dlp 无法解密其 Cookie —— 这不是本程序的 bug，官方也暂无修复。",
            style="Dim.TLabel", wraplength=560, justify="left",
        ).pack(anchor="w", pady=(2, 12))

        # ---------------------------------------------------------- 诊断
        diag = ttk.Labelframe(pad, text=" 环境诊断 ", padding=(12, 10))
        diag.pack(fill="x")
        d = ck.diagnose()
        self._kv(diag, 0, "已安装浏览器",
                 "、".join(ck.BROWSER_LABELS.get(b, b) for b in d["installed"]) or "未检测到")
        self._kv(diag, 1, "当前 Cookie 配置", self._current_desc())
        self._kv(diag, 2, "App-Bound 限制",
                 ("存在：" + d["appbound_reason"]) if d["appbound_risk"] else "无（可直接读取）")
        ff = [p["name"] for p in d["firefox_profiles"] if p["exists"]]
        self._kv(diag, 3, "Firefox 配置",
                 ("可用：" + "、".join(ff)) if ff else "未安装或没有配置文件")

        # ---------------------------------------------------------- 方案
        plans = ttk.Labelframe(pad, text=" 推荐方案（按可靠度排序） ", padding=(12, 10))
        plans.pack(fill="x", pady=(12, 0))

        r1 = ttk.Frame(plans)
        r1.pack(fill="x", pady=(0, 6))
        ttk.Label(r1, text="方案 1 · 手动填写 Cookie", width=24).pack(side="left")
        ttk.Button(r1, text="✍ 手动粘贴", command=self._manual).pack(side="left")
        ttk.Label(r1, text="从 F12 请求头复制 Cookie 一行即可，不用装扩展（最直接）",
                  style="Dim.TLabel").pack(side="left", padx=8)

        r2 = ttk.Frame(plans)
        r2.pack(fill="x", pady=(0, 6))
        ttk.Label(r2, text="方案 2 · 使用 Firefox", width=24).pack(side="left")
        self.btn_ff = ttk.Button(r2, text="一键切换到 Firefox", command=self._use_firefox)
        self.btn_ff.pack(side="left")
        ttk.Label(r2, text="Firefox 的 Cookie 未加密，可直接读取",
                  style="Dim.TLabel").pack(side="left", padx=8)

        r3 = ttk.Frame(plans)
        r3.pack(fill="x", pady=(0, 6))
        ttk.Label(r3, text="方案 3 · cookies.txt", width=24).pack(side="left")
        ttk.Button(r3, text="选择 cookies.txt…", command=self._pick_file).pack(side="left")
        ttk.Button(r3, text="获取导出扩展", command=lambda: webbrowser.open(EXT_URL)).pack(side="left", padx=6)
        ttk.Label(r3, text="用扩展导出后选择该文件，兼容性最好",
                  style="Dim.TLabel").pack(side="left", padx=8)

        r4 = ttk.Frame(plans)
        r4.pack(fill="x")
        ttk.Label(r4, text="方案 4 · 检查现状", width=24).pack(side="left")
        ttk.Button(r4, text="校验当前 Cookie 配置", command=self._validate).pack(side="left")
        ttk.Button(r4, text="查看官方说明", command=lambda: webbrowser.open(ISSUE_URL)).pack(side="left", padx=6)

        if not d["firefox_ok"]:
            self.btn_ff.configure(state="disabled")

        # ---------------------------------------------------------- 输出
        self.out = tk.Text(pad, height=9, wrap="word", relief="flat", font=("Consolas", 9),
                           bg="#ffffff", fg="#374151", highlightthickness=1,
                           highlightbackground="#e5e7eb", state="disabled")
        self.out.pack(fill="both", expand=True, pady=(12, 10))

        bar = ttk.Frame(pad)
        bar.pack(fill="x")
        ttk.Button(bar, text="关闭", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="应用并保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=6)

        self._log("提示：方案 1 ~ 3 任选其一即可，方案 1（手动粘贴）不需要安装任何东西。")
        self._log(f"当前配置：{self._current_desc()}")
        if d["appbound_risk"] and not d["firefox_ok"]:
            self._log("⚠ 检测到 Chromium 系浏览器且没有 Firefox —— 推荐方案 1（手动粘贴 Cookie）"
                      "或方案 3（cookies.txt）。")
        elif d["appbound_risk"]:
            self._log("✔ 可用方案 1（手动粘贴）或方案 2（Firefox）。")

        self.update_idletasks()

    # ------------------------------------------------------------ 小组件
    def _kv(self, parent: ttk.Frame, row: int, key: str, value: str) -> None:
        ttk.Label(parent, text=key, width=16).grid(row=row, column=0, sticky="nw", pady=2)
        ttk.Label(parent, text=value, style="Dim.TLabel", wraplength=430,
                  justify="left").grid(row=row, column=1, sticky="w", pady=2)
        parent.columnconfigure(1, weight=1)

    def _log(self, msg: str) -> None:
        self.out.configure(state="normal")
        self.out.insert("end", msg + "\n")
        self.out.see("end")
        self.out.configure(state="disabled")

    def _current_desc(self) -> str:
        manual = getattr(self.cfg, "manual_cookies", None) or {}
        if manual:
            return f"手动填写（{ck.manual_cookie_summary(manual)}）"
        if self.cfg.cookies_file.strip():
            p = Path(self.cfg.cookies_file)
            return f"cookies.txt：{p.name}（{'存在' if p.is_file() else '文件不存在'}）"
        if self.cfg.cookies_from_browser.strip():
            b = self.cfg.cookies_from_browser.strip()
            risky = " ⚠ 受 App-Bound 限制" if b in ck.CHROMIUM_BROWSERS else ""
            return f"浏览器：{ck.BROWSER_LABELS.get(b, b)}{risky}"
        return "未配置（仅能下载公开内容，画质可能受限）"

    # ------------------------------------------------------------ 动作
    def _manual(self) -> None:
        from .manual_cookie_dialog import ManualCookieDialog

        try:
            self.grab_release()
        except Exception:
            pass
        dlg = ManualCookieDialog(self, on_saved=self._on_manual_saved)
        self.wait_window(dlg)
        try:
            self.grab_set()
        except Exception:
            pass

    def _on_manual_saved(self) -> None:
        self.cfg = ConfigStore.get()
        self._log("✔ 手动 Cookie 已保存: " + ck.manual_cookie_summary(self.cfg.manual_cookies or {}))

    def _use_firefox(self) -> None:
        profs = ck.find_firefox_profiles()
        ok = [p for p in profs if p["exists"]]
        if not ok:
            messagebox.showwarning("未找到 Firefox", "未检测到带 Cookie 的 Firefox 配置文件。", parent=self)
            return
        self.cfg.cookies_from_browser = "firefox"
        ConfigStore.save()
        self._log("✔ 已切换为 Firefox 读取 Cookie，保存设置后重新解析即可生效。")
        self._log("   提示：请先在 Firefox 中登录目标网站（抖音 / B 站 / YouTube 等）。")

    def _pick_file(self) -> None:
        f = filedialog.askopenfilename(parent=self, title="选择 cookies.txt",
                                       filetypes=[("Cookies 文本", "*.txt"), ("所有文件", "*.*")])
        if not f:
            return
        self.cfg.cookies_file = f
        self.cfg.cookies_from_browser = ""
        ConfigStore.save()
        self._log(f"已选择：{f}")
        self._validate()

    def _validate(self) -> None:
        path = self.cfg.cookies_file.strip()
        if path:
            info = ck.parse_cookies_txt(path)
            self._log(f"文件大小：{human_bytes(Path(path).stat().st_size) if Path(path).is_file() else '—'}"
                      f"　共 {info.total} 条 Cookie，覆盖 {len(info.domains)} 个域名")
            self._log("主要域名：" + ("、".join(info.domain_list(8)) or "无"))
            for pf in self.platforms[:4]:
                ok, msg, _ = ck.check_cookies_for_platform(path, pf)
                self._log(("  ✔ " if ok else "  ✘ ") + f"[{pf}] {msg}")
            if not any(ck.check_cookies_for_platform(path, pf)[0] for pf in self.platforms[:4]):
                self._log("  → 建议在扩展里选择「导出全部 Cookie」，并确认已登录目标网站。")
        elif self.cfg.cookies_from_browser.strip():
            b = self.cfg.cookies_from_browser.strip()
            if b in ck.CHROMIUM_BROWSERS and ck.appbound_risk()[0]:
                self._log(f"✘ {ck.BROWSER_LABELS.get(b, b)} 受 App-Bound 加密限制，无法读取 Cookie。")
                self._log("  → 请使用方案 1（Firefox）或方案 2（cookies.txt）。")
            elif b == "firefox":
                profs = [p for p in ck.find_firefox_profiles() if p["exists"]]
                self._log("✔ Firefox 配置可用：" + "、".join(p["name"] for p in profs)
                          if profs else "✘ 未找到 Firefox 配置文件")
            else:
                self._log(f"已配置 {b}，将在下次解析时验证。")
        else:
            self._log("当前未配置任何 Cookie。")

    def _save(self) -> None:
        ConfigStore.save()
        self._log("✔ 设置已保存。请在任务列表右键「重新下载」以使用新的 Cookie 配置。")
