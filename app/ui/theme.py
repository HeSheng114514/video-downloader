# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""界面主题：配色表 + ttk 样式。

设计要点
--------
* 三层表面：画布(canvas) → 卡片(card) → 输入框(field)，层次分明
* 卡片用 tk.Frame 的 highlightthickness 画 1px 边框（ttk 在 clam 下边框不稳）
* 按钮分三档：Primary（主操作，实心强调色）/ Secondary（次要，浅底描边）/ Ghost（无边框）
* 浅色、深色两套配色，均为低饱和现代风格
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "canvas": "#f2f4f7",      # 最底层画布
        "card": "#ffffff",        # 卡片表面
        "card_alt": "#f8fafc",    # 卡片内次级区域
        "field": "#ffffff",       # 输入框
        "border": "#e3e6eb",      # 卡片描边
        "border_strong": "#cfd4dc",
        "text": "#111827",
        "text_dim": "#6b7280",
        "text_mute": "#9ca3af",
        "accent": "#2f6fed",
        "accent_hover": "#1e5bd6",
        "accent_soft": "#eaf1ff",
        "accent_text": "#ffffff",
        "success": "#12805c",
        "warn": "#b45309",
        "error": "#d92d20",
        "info": "#2f6fed",
        "stripe": "#fafbfc",
        "sel": "#dbe8ff",
        "head": "#f4f6f9",
        "hover": "#f3f5f8",
    },
    "dark": {
        "canvas": "#151619",
        "card": "#1e2024",
        "card_alt": "#232529",
        "field": "#17181c",
        "border": "#2e3137",
        "border_strong": "#3d4148",
        "text": "#e8eaed",
        "text_dim": "#9aa1ab",
        "text_mute": "#6f7681",
        "accent": "#5b8def",
        "accent_hover": "#7aa4f5",
        "accent_soft": "#1f2937",
        "accent_text": "#0f1115",
        "success": "#4ade80",
        "warn": "#fbbf24",
        "error": "#f87171",
        "info": "#7aa4f5",
        "stripe": "#1b1d21",
        "sel": "#2b3a55",
        "head": "#232529",
        "hover": "#272a2f",
    },
}


def palette(theme: str) -> dict[str, str]:
    return THEMES.get(theme, THEMES["light"])


def make_card(parent: tk.Misc, colors: dict[str, str], **kw) -> tk.Frame:
    """创建一张带 1px 描边的卡片（classic tk.Frame，边框最稳）。"""
    opts = dict(bg=colors["card"], highlightthickness=1,
                highlightbackground=colors["border"], highlightcolor=colors["border"],
                bd=0)
    opts.update(kw)
    return tk.Frame(parent, **opts)


def make_divider(parent: tk.Misc, colors: dict[str, str], orient: str = "h",
                 thickness: int = 1, color: str | None = None) -> tk.Frame:
    """1px 分隔线（用 tk.Frame 实现，比 ttk.Separator 更可控）。"""
    if orient == "h":
        return tk.Frame(parent, height=thickness, bg=color or colors["border"], bd=0,
                        highlightthickness=0)
    return tk.Frame(parent, width=thickness, bg=color or colors["border"], bd=0,
                    highlightthickness=0)


def make_text(parent: tk.Misc, colors: dict[str, str], *, mono: bool = False,
              height: int = 4, wrap: str = "none", **kw) -> tk.Text:
    """统一风格的文本框。"""
    opts = dict(
        height=height, wrap=wrap, relief="flat", bd=0,
        font=(MONO_FAMILY, 10) if mono else (FONT_FAMILY, 10),
        bg=colors["field"], fg=colors["text"], insertbackground=colors["text"],
        selectbackground=colors["sel"], selectforeground=colors["text"],
        highlightthickness=1, highlightbackground=colors["border"],
        highlightcolor=colors["accent"], padx=8, pady=6, undo=True,
    )
    opts.update(kw)
    return tk.Text(parent, **opts)


def apply_theme(root: tk.Misc, theme: str) -> dict[str, str]:
    """配置 ttk 样式并返回配色表。"""
    c = palette(theme)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    base = (FONT_FAMILY, 10)
    small = (FONT_FAMILY, 9)
    tiny = (FONT_FAMILY, 8)
    bold = (FONT_FAMILY, 10, "bold")
    card_title = (FONT_FAMILY, 11, "bold")
    brand = (FONT_FAMILY, 13, "bold")

    root.configure(bg=c["canvas"])

    # ---------------------------------------------------------- 基础
    style.configure(".", background=c["canvas"], foreground=c["text"], font=base,
                    fieldbackground=c["field"], bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"], focuscolor=c["accent"])
    style.configure("TFrame", background=c["canvas"])
    style.configure("Canvas.TFrame", background=c["canvas"])
    style.configure("Card.TFrame", background=c["card"])
    style.configure("CardAlt.TFrame", background=c["card_alt"])

    style.configure("TLabel", background=c["canvas"], foreground=c["text"], font=base)
    style.configure("Card.TLabel", background=c["card"], foreground=c["text"], font=base)
    style.configure("CardTitle.TLabel", background=c["card"], foreground=c["text"], font=card_title)
    style.configure("CardHint.TLabel", background=c["card"], foreground=c["text_mute"], font=small)
    style.configure("CardDim.TLabel", background=c["card"], foreground=c["text_dim"], font=small)
    style.configure("CardBold.TLabel", background=c["card"], foreground=c["text"], font=bold)
    style.configure("Dim.TLabel", background=c["canvas"], foreground=c["text_dim"], font=small)
    style.configure("Bold.TLabel", background=c["canvas"], foreground=c["text"], font=bold)

    # 顶栏
    style.configure("Header.TFrame", background=c["card"])
    style.configure("HeaderBrand.TLabel", background=c["card"], foreground=c["accent"], font=brand)
    style.configure("HeaderHint.TLabel", background=c["card"], foreground=c["text_mute"], font=small)
    style.configure("HeaderChip.TLabel", background=c["accent_soft"], foreground=c["accent"],
                    font=small, padding=(6, 2))

    # 状态栏
    style.configure("StatusBar.TFrame", background=c["card"])
    style.configure("Status.TLabel", background=c["card"], foreground=c["text_dim"], font=small)
    style.configure("StatusStrong.TLabel", background=c["card"], foreground=c["text"], font=small)

    # 卡片内的输入控件
    # clam 复选框指示器的四个关键选项（实测得出）：
    #   indicatorbackground = 方框底色
    #   indicatorforeground = 「勾」的颜色
    #   upper/lowerbordercolor = 边框色（不设会露出默认浅蓝灰，深色下很突兀）
    cb_common = dict(
        indicatorbackground=c["field"], indicatorforeground=c["text"],
        upperbordercolor=c["border_strong"], lowerbordercolor=c["border_strong"],
        indicatorsize=15, indicatorrelief="flat", focuscolor=c["accent"], padding=(2, 2),
    )
    cb_map = dict(
        indicatorbackground=[("disabled", c["card_alt"]),
                             ("selected", c["accent"]),
                             ("pressed", c["hover"])],
        indicatorforeground=[("disabled", c["text_mute"]),
                             ("selected", c["accent_text"])],
        upperbordercolor=[("selected", c["accent"]), ("disabled", c["border"])],
        lowerbordercolor=[("selected", c["accent"]), ("disabled", c["border"])],
    )
    style.configure("Card.TCheckbutton", background=c["card"], foreground=c["text"],
                    font=base, **cb_common)
    style.map("Card.TCheckbutton", background=[("active", c["card"])],
              foreground=[("disabled", c["text_mute"])], **cb_map)
    style.configure("TCheckbutton", background=c["canvas"], foreground=c["text"],
                    font=base, **cb_common)
    style.map("TCheckbutton", background=[("active", c["canvas"])], **cb_map)
    style.configure("TRadiobutton", background=c["canvas"], foreground=c["text"], font=base,
                    focuscolor=c["accent"], indicatorbackground=c["field"],
                    indicatorcolor=c["accent"], indicatorrelief="flat",
                    bordercolor=c["border_strong"], lightcolor=c["border_strong"],
                    darkcolor=c["border_strong"])

    # ---------------------------------------------------------- 按钮
    pad_v = 7
    style.configure("TButton", background=c["card_alt"], foreground=c["text"], font=base,
                    borderwidth=1, bordercolor=c["border"], focusthickness=0,
                    padding=(12, pad_v), relief="flat", anchor="center",
                    lightcolor=c["border"], darkcolor=c["border"])
    style.map("TButton",
              background=[("pressed", c["hover"]), ("active", c["hover"]),
                          ("disabled", c["card_alt"])],
              foreground=[("disabled", c["text_mute"])],
              bordercolor=[("active", c["border_strong"])],
              lightcolor=[("active", c["border_strong"])],
              darkcolor=[("active", c["border_strong"])])

    style.configure("Primary.TButton", background=c["accent"], foreground=c["accent_text"],
                    font=bold, borderwidth=1, bordercolor=c["accent"], padding=(16, pad_v + 1),
                    relief="flat", lightcolor=c["accent"], darkcolor=c["accent"])
    style.map("Primary.TButton",
              background=[("pressed", c["accent_hover"]), ("active", c["accent_hover"]),
                          ("disabled", c["border_strong"])],
              foreground=[("disabled", c["card"])],
              bordercolor=[("active", c["accent_hover"])],
              lightcolor=[("active", c["accent_hover"])],
              darkcolor=[("active", c["accent_hover"])])

    style.configure("Secondary.TButton", background=c["card"], foreground=c["text"], font=base,
                    borderwidth=1, bordercolor=c["border_strong"], padding=(12, pad_v),
                    relief="flat", lightcolor=c["border_strong"], darkcolor=c["border_strong"])
    style.map("Secondary.TButton",
              background=[("pressed", c["hover"]), ("active", c["hover"])],
              bordercolor=[("active", c["accent"])],
              lightcolor=[("active", c["accent"])], darkcolor=[("active", c["accent"])])

    # 兼容旧样式名（对话框里仍在使用）
    style.configure("Accent.TButton", background=c["accent"], foreground=c["accent_text"],
                    font=bold, borderwidth=1, bordercolor=c["accent"], padding=(14, pad_v + 1),
                    relief="flat", lightcolor=c["accent"], darkcolor=c["accent"])
    style.map("Accent.TButton",
              background=[("pressed", c["accent_hover"]), ("active", c["accent_hover"]),
                          ("disabled", c["border_strong"])],
              foreground=[("disabled", c["card"])],
              bordercolor=[("active", c["accent_hover"])])

    style.configure("Ghost.TButton", background=c["card"], foreground=c["text_dim"], font=small,
                    borderwidth=0, padding=(8, 4), relief="flat")
    style.map("Ghost.TButton",
              background=[("pressed", c["hover"]), ("active", c["hover"])],
              foreground=[("active", c["text"])])

    style.configure("Tool.TButton", background=c["card"], foreground=c["text_dim"], font=base,
                    borderwidth=0, padding=(9, 5), relief="flat")
    style.map("Tool.TButton",
              background=[("pressed", c["hover"]), ("active", c["hover"])],
              foreground=[("active", c["accent"])])

    # ---------------------------------------------------------- 输入类
    style.configure("TEntry", fieldbackground=c["field"], foreground=c["text"], font=base,
                    insertcolor=c["text"], bordercolor=c["border"], lightcolor=c["border"],
                    darkcolor=c["border"], padding=(6, 5), relief="flat")
    style.map("TEntry", bordercolor=[("focus", c["accent"])],
              lightcolor=[("focus", c["accent"])], darkcolor=[("focus", c["accent"])])
    style.configure("TCombobox", fieldbackground=c["field"], background=c["card_alt"],
                    foreground=c["text"], arrowcolor=c["text_dim"], bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"], padding=(6, 5),
                    relief="flat", arrowsize=14)
    style.map("TCombobox",
              fieldbackground=[("readonly", c["field"]), ("disabled", c["card_alt"])],
              foreground=[("readonly", c["text"]), ("disabled", c["text_mute"])],
              bordercolor=[("focus", c["accent"]), ("active", c["border_strong"])],
              arrowcolor=[("active", c["accent"])])
    root.option_add("*TCombobox*Listbox.background", c["card"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["accent_text"])
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.font", base)

    style.configure("TSpinbox", fieldbackground=c["field"], foreground=c["text"],
                    arrowcolor=c["text_dim"], bordercolor=c["border"], lightcolor=c["border"],
                    darkcolor=c["border"], padding=(6, 5), arrowsize=14, relief="flat")
    style.map("TSpinbox", bordercolor=[("focus", c["accent"])])

    # ---------------------------------------------------------- 表格
    style.configure("Treeview", background=c["card"], fieldbackground=c["card"],
                    foreground=c["text"], rowheight=30, font=base, borderwidth=0,
                    relief="flat")
    style.map("Treeview",
              background=[("selected", c["sel"])],
              foreground=[("selected", c["text"])])
    style.configure("Treeview.Heading", background=c["head"], foreground=c["text_dim"],
                    font=small, relief="flat", padding=(8, 7), borderwidth=0)
    style.map("Treeview.Heading", background=[("active", c["hover"])],
              foreground=[("active", c["text"])])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # 去掉外框

    # ---------------------------------------------------------- 其他
    # Notebook：clam 默认会给标签页画 3D 白色边框，必须显式指定三个边框色
    style.configure("TNotebook", background=c["canvas"], borderwidth=0,
                    bordercolor=c["border"], lightcolor=c["canvas"], darkcolor=c["canvas"],
                    tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", background=c["canvas"], foreground=c["text_dim"],
                    padding=(18, 9), font=base, borderwidth=0, relief="flat",
                    bordercolor=c["border"], lightcolor=c["canvas"], darkcolor=c["canvas"],
                    focuscolor=c["accent"])
    style.map("TNotebook.Tab",
              background=[("selected", c["card"]), ("active", c["hover"])],
              foreground=[("selected", c["accent"]), ("active", c["text"])],
              bordercolor=[("selected", c["border"]), ("active", c["border"])],
              lightcolor=[("selected", c["card"]), ("active", c["canvas"])],
              darkcolor=[("selected", c["card"]), ("active", c["canvas"])],
              expand=[("selected", (0, 0, 0, 0))])

    style.configure("TLabelframe", background=c["canvas"], bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=c["canvas"], foreground=c["text_dim"],
                    font=small)

    style.configure("Horizontal.TProgressbar", background=c["accent"], troughcolor=c["card_alt"],
                    bordercolor=c["border"], lightcolor=c["accent"], darkcolor=c["accent"],
                    thickness=6)
    style.configure("TSeparator", background=c["border"])

    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=c["border_strong"],
                        troughcolor=c["canvas"], bordercolor=c["canvas"],
                        arrowcolor=c["text_mute"], relief="flat", arrowsize=13,
                        gripcount=0)
        style.map(f"{orient}.TScrollbar",
                  background=[("active", c["text_mute"])])

    # 供 _on_settings_saved 等刷新时复用
    return c
