# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""手动填写 Cookie 对话框。

相比「浏览器读取」与「cookies.txt 文件」，手动粘贴是最直接的方式：
不受 App-Bound 加密影响，也不需要安装任何扩展。
用户从 DevTools 的请求头里复制 Cookie 一行即可。
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .. import cookies as ck
from ..config import ConfigStore
from ..net import shared_client

# 站点选择项：(显示名, 域名)
SITE_CHOICES: list[tuple[str, str]] = [
    ("哔哩哔哩", ck.PLATFORM_DOMAINS["bilibili"]),
    ("抖音", ck.PLATFORM_DOMAINS["douyin"]),
    ("快手", ck.PLATFORM_DOMAINS["kuaishou"]),
    ("YouTube", ck.PLATFORM_DOMAINS["youtube"]),
    ("TikTok", ck.PLATFORM_DOMAINS["tiktok"]),
    ("小红书", ck.PLATFORM_DOMAINS["xiaohongshu"]),
    ("微博", ck.PLATFORM_DOMAINS["weibo"]),
    ("X / Twitter", ck.PLATFORM_DOMAINS["twitter"]),
    ("自定义域名…", ""),
]

HELP_TEXT = (
    "获取方法（推荐，能拿到 HttpOnly 的关键 Cookie）：\n"
    "  1. 用浏览器登录目标网站（例如 B 站）\n"
    "  2. 按 F12 → Network（网络）→ 刷新页面 → 点任意一个请求\n"
    "  3. 在 Request Headers（请求标头）里找到 Cookie: 那一行，整行复制\n"
    "  4. 粘贴到下面文本框，选好站点，点「解析并保存」\n"
    "\n"
    "※ 不要用 console 里的 document.cookie —— 它取不到 HttpOnly 的 Cookie\n"
    "   （如 B 站的 SESSDATA、抖音的 ttwid），会导致登录态不生效。\n"
    "※ 也支持直接粘贴整段「Copy as cURL」，程序会自动提取其中的 Cookie。"
)


class ManualCookieDialog(tk.Toplevel):
    def __init__(self, master, on_saved=None) -> None:
        super().__init__(master)
        self.cfg = ConfigStore.get()
        self.on_saved = on_saved
        self.title("手动填写 Cookie")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        pad = ttk.Frame(self, padding=16)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="手动填写 Cookie", style="Bold.TLabel").pack(anchor="w")
        ttk.Label(pad, text=HELP_TEXT, style="Dim.TLabel", justify="left",
                  wraplength=600).pack(anchor="w", pady=(4, 12))

        # ---------------------------------------------------------- 站点
        row = ttk.Frame(pad)
        row.pack(fill="x")
        ttk.Label(row, text="站点", width=8).pack(side="left")
        self.var_site = tk.StringVar(value=SITE_CHOICES[0][0])
        cmb = ttk.Combobox(row, state="readonly", textvariable=self.var_site, width=16,
                           values=[s[0] for s in SITE_CHOICES])
        cmb.pack(side="left")
        cmb.bind("<<ComboboxSelected>>", lambda e: self._on_site_change())
        ttk.Label(row, text="域名", width=6).pack(side="left", padx=(12, 0))
        self.var_domain = tk.StringVar(value=SITE_CHOICES[0][1])
        ttk.Entry(row, textvariable=self.var_domain, width=28).pack(side="left")
        ttk.Label(row, text="（决定 Cookie 作用范围，一般不用改）",
                  style="Dim.TLabel").pack(side="left", padx=6)

        # ---------------------------------------------------------- 输入
        ttk.Label(pad, text="粘贴 Cookie 字符串").pack(anchor="w", pady=(12, 4))
        self.txt = tk.Text(pad, height=6, wrap="word", relief="flat", font=("Consolas", 9),
                           bg="#ffffff", fg="#111827", highlightthickness=1,
                           highlightbackground="#e5e7eb", insertbackground="#111827")
        self.txt.pack(fill="x")
        self.txt.bind("<KeyRelease>", lambda e: self._preview())
        self.txt.bind("<<Paste>>", lambda e: self.after(60, self._preview))

        opt = ttk.Frame(pad)
        opt.pack(fill="x", pady=(8, 0))
        ttk.Button(opt, text="解析预览", command=self._preview).pack(side="left")
        ttk.Button(opt, text="校验有效性（联网）", command=self._validate_input).pack(side="left", padx=6)
        ttk.Button(opt, text="校验已保存", command=self._validate_saved).pack(side="left")
        ttk.Button(opt, text="清空输入", command=self._clear_input).pack(side="left", padx=6)
        self.lbl_preview = ttk.Label(opt, text="", style="Dim.TLabel")
        self.lbl_preview.pack(side="left", padx=10)

        # ---------------------------------------------------------- 已保存
        ttk.Label(pad, text="已保存的 Cookie").pack(anchor="w", pady=(14, 4))
        box = ttk.Frame(pad)
        box.pack(fill="both", expand=True)
        cols = ("domain", "count", "names")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=5, selectmode="extended")
        for col, text, width in (("domain", "域名", 170), ("count", "条数", 60), ("names", "包含的 Cookie", 340)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w" if col != "count" else "center")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        ttk.Button(box, text="删除选中", command=self._delete_selected).pack(side="left", padx=(6, 0), anchor="n")

        # ---------------------------------------------------------- 底部
        bar = ttk.Frame(pad)
        bar.pack(fill="x", pady=(14, 0))
        ttk.Button(bar, text="关闭", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="解析并保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=6)

        self._refresh_tree()
        self.update_idletasks()

    # ------------------------------------------------------------ 行为
    def _on_site_change(self) -> None:
        for label, domain in SITE_CHOICES:
            if label == self.var_site.get():
                self.var_domain.set(domain)
                break
        self._preview()

    def _clear_input(self) -> None:
        self.txt.delete("1.0", "end")
        self._preview()

    def _pairs(self) -> dict[str, str]:
        return ck.parse_cookie_string(self.txt.get("1.0", "end"))

    def _preview(self) -> None:
        pairs = self._pairs()
        if not pairs:
            self.lbl_preview.configure(text="尚未识别到 Cookie", foreground="#6b7280")
            return
        platform = ck.guess_platform(pairs.keys())
        names = list(pairs.keys())
        shown = "、".join(names[:5]) + ("…" if len(names) > 5 else "")
        hint = ""
        if platform:
            key = ck.PLATFORM_DOMAINS.get(platform, "")
            if key and not self.var_domain.get().strip():
                self.var_domain.set(key)
            need = ck.EXPECTED_COOKIES.get(platform, ((), ()))[1]
            hit = [n for n in names if n in need]
            hint = f"　识别为 {platform}，含关键 Cookie：{'、'.join(hit)}" if hit else f"　识别为 {platform}，但未见关键 Cookie"
        self.lbl_preview.configure(
            text=f"识别到 {len(pairs)} 条：{shown}{hint}", foreground="#16a34a")

    def _validate_input(self) -> None:
        """联网校验当前输入框里的 Cookie 是否仍然有效。"""
        pairs = self._pairs()
        if not pairs:
            messagebox.showwarning("没有内容", "请先粘贴 Cookie 字符串。", parent=self)
            return
        domain = (self.var_domain.get().strip() or
                  ck.PLATFORM_DOMAINS.get(ck.guess_platform(pairs) or "", "") or ".")
        platform = ck.guess_platform(pairs) or ck.platform_from_domain(domain) or ""
        self._run_validity(platform, ck.format_cookie_string(pairs), domain)

    def _validate_saved(self) -> None:
        saved = self.cfg.manual_cookies or {}
        if not saved:
            messagebox.showinfo("暂无内容", "还没有保存任何 Cookie。", parent=self)
            return
        domain, cookie_str = next(iter(saved.items()))
        platform = ck.guess_platform(ck.parse_cookie_string(cookie_str)) or \
            ck.platform_from_domain(domain) or ""
        self._run_validity(platform, cookie_str, domain)

    def _run_validity(self, platform: str, cookie_str: str, domain: str) -> None:
        self.lbl_preview.configure(text="正在联网校验 Cookie 有效性…", foreground="#d97706")

        def work() -> None:
            try:
                client = shared_client(self.cfg.proxy, self.cfg.insecure)
                ok, msg = ck.check_cookie_validity(platform or "", cookie_str, client)
            except Exception as e:
                ok, msg = None, f"校验出错：{type(e).__name__} {e}"
            color = "#16a34a" if ok else ("#dc2626" if ok is False else "#6b7280")
            icon = "✔" if ok else ("✘" if ok is False else "•")
            try:
                self.after(0, lambda: self.lbl_preview.configure(
                    text=f"{icon} [{domain}] {msg}", foreground=color))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for domain, cookie_str in sorted((self.cfg.manual_cookies or {}).items()):
            pairs = ck.parse_cookie_string(cookie_str)
            names = "、".join(list(pairs.keys())[:6]) + ("…" if len(pairs) > 6 else "")
            self.tree.insert("", "end", values=(domain, len(pairs), names))
        if not self.cfg.manual_cookies:
            self.tree.insert("", "end", values=("（暂无，请在上方粘贴后保存）", "", ""))

    def _delete_selected(self) -> None:
        items = self.tree.selection()
        if not items:
            return
        removed = []
        for item in items:
            dom = self.tree.item(item, "values")[0]
            if dom in (self.cfg.manual_cookies or {}):
                self.cfg.manual_cookies.pop(dom, None)
                removed.append(dom)
        if removed:
            ConfigStore.save()
            self._refresh_tree()
            if self.on_saved:
                self.on_saved()

    def _save(self) -> None:
        domain = self.var_domain.get().strip()
        pairs = self._pairs()
        if not pairs:
            messagebox.showwarning("没有内容", "请先粘贴 Cookie 字符串。", parent=self)
            return
        if not domain:
            messagebox.showwarning("缺少域名", "请选择站点或填写域名。", parent=self)
            return
        if not domain.startswith("."):
            domain = "." + domain
        existing = ck.parse_cookie_string(self.cfg.manual_cookies.get(domain, ""))
        merged = {**existing, **pairs}
        self.cfg.manual_cookies[domain] = ck.format_cookie_string(merged)
        # 手动 Cookie 与文件互斥，避免优先级混淆
        if self.cfg.cookies_file.strip():
            self.cfg.cookies_file = ""
        ConfigStore.save()
        self._refresh_tree()
        self._clear_input()
        saved_platform = ck.guess_platform(merged.keys())
        msg = f"已保存 {len(merged)} 条 Cookie 到 {domain}"
        if saved_platform:
            need = ck.EXPECTED_COOKIES.get(saved_platform, ((), ()))[1]
            miss = [k for k in need if k not in merged]
            msg += f"（{saved_platform} 登录态已就绪）" if not miss else f"，仍缺少 {miss[0]} 等关键 Cookie"
        self.lbl_preview.configure(text=msg, foreground="#16a34a")
        if self.on_saved:
            self.on_saved()
        # 保存后自动联网确认一次登录态是否真的有效
        self._run_validity(ck.guess_platform(merged.keys()) or
                           ck.platform_from_domain(domain) or "", merged and
                           ck.format_cookie_string(merged), domain)
