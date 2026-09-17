# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""界面主题（浅色 / 深色）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f4f5f7",
        "panel": "#ffffff",
        "panel_alt": "#fafbfc",
        "border": "#dfe3e8",
        "text": "#1f2329",
        "text_dim": "#6b7280",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "accent_text": "#ffffff",
        "success": "#16a34a",
        "warn": "#d97706",
        "error": "#dc2626",
        "info": "#2563eb",
        "striped": "#f7f8fa",
        "sel": "#dbeafe",
        "input_bg": "#ffffff",
        "tree_head": "#eef1f5",
    },
    "dark": {
        "bg": "#1e1f22",
        "panel": "#2b2d31",
        "panel_alt": "#313338",
        "border": "#3f4147",
        "text": "#e6e6e6",
        "text_dim": "#9aa0a6",
        "accent": "#3b82f6",
        "accent_hover": "#2563eb",
        "accent_text": "#ffffff",
        "success": "#4ade80",
        "warn": "#fbbf24",
        "error": "#f87171",
        "info": "#60a5fa",
        "striped": "#26282c",
        "sel": "#374151",
        "input_bg": "#1e1f22",
        "tree_head": "#26282c",
    },
}


def palette(theme: str) -> dict[str, str]:
    return THEMES.get(theme, THEMES["light"])


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
    bold = (FONT_FAMILY, 10, "bold")
    title = (FONT_FAMILY, 12, "bold")

    root.configure(bg=c["bg"])
    style.configure(".", background=c["bg"], foreground=c["text"], font=base,
                    fieldbackground=c["input_bg"], bordercolor=c["border"],
                    lightcolor=c["border"], darkcolor=c["border"])
    style.configure("TFrame", background=c["bg"])
    style.configure("Panel.TFrame", background=c["panel"])
    style.configure("TLabel", background=c["bg"], foreground=c["text"], font=base)
    style.configure("Panel.TLabel", background=c["panel"], foreground=c["text"])
    style.configure("Dim.TLabel", background=c["bg"], foreground=c["text_dim"], font=small)
    style.configure("PanelDim.TLabel", background=c["panel"], foreground=c["text_dim"], font=small)
    style.configure("Title.TLabel", background=c["panel"], foreground=c["text"], font=title)
    style.configure("Bold.TLabel", background=c["bg"], foreground=c["text"], font=bold)
    style.configure("Status.TLabel", background=c["panel_alt"], foreground=c["text_dim"], font=small)

    style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"],
                    relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=c["bg"], foreground=c["text_dim"], font=small)

    style.configure("TButton", background=c["panel"], foreground=c["text"], font=base,
                    borderwidth=1, focusthickness=0, padding=(10, 5), relief="flat")
    style.map("TButton",
              background=[("active", c["panel_alt"]), ("disabled", c["bg"])],
              foreground=[("disabled", c["text_dim"])])
    style.configure("Accent.TButton", background=c["accent"], foreground=c["accent_text"],
                    font=bold, padding=(12, 6), relief="flat")
    style.map("Accent.TButton", background=[("active", c["accent_hover"]),
                                            ("disabled", c["border"])])
    style.configure("Ghost.TButton", background=c["bg"], foreground=c["text_dim"], padding=(8, 4))
    style.map("Ghost.TButton", background=[("active", c["panel_alt"])])

    style.configure("TCheckbutton", background=c["bg"], foreground=c["text"], font=base)
    style.map("TCheckbutton", background=[("active", c["bg"])])
    style.configure("Panel.TCheckbutton", background=c["panel"], foreground=c["text"])
    style.configure("TRadiobutton", background=c["bg"], foreground=c["text"])

    style.configure("TEntry", fieldbackground=c["input_bg"], foreground=c["text"],
                    insertcolor=c["text"], bordercolor=c["border"], padding=4)
    style.configure("TCombobox", fieldbackground=c["input_bg"], background=c["panel"],
                    foreground=c["text"], arrowcolor=c["text"], padding=3)
    style.map("TCombobox", fieldbackground=[("readonly", c["input_bg"])],
              foreground=[("readonly", c["text"])])
    root.option_add("*TCombobox*Listbox.background", c["input_bg"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])

    style.configure("TSpinbox", fieldbackground=c["input_bg"], foreground=c["text"],
                    arrowcolor=c["text"], padding=3)

    style.configure("Treeview", background=c["panel"], fieldbackground=c["panel"],
                    foreground=c["text"], rowheight=30, font=base, borderwidth=0)
    style.configure("Treeview.Heading", background=c["tree_head"], foreground=c["text_dim"],
                    font=small, relief="flat", padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", c["border"])])
    style.map("Treeview", background=[("selected", c["sel"])],
              foreground=[("selected", c["text"])])

    style.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
    style.configure("TNotebook.Tab", background=c["panel_alt"], foreground=c["text_dim"],
                    padding=(16, 8), font=base)
    style.map("TNotebook.Tab", background=[("selected", c["panel"])],
              foreground=[("selected", c["text"])])

    style.configure("Horizontal.TProgressbar", background=c["accent"],
                    troughcolor=c["panel_alt"], bordercolor=c["border"], lightcolor=c["accent"],
                    darkcolor=c["accent"])
    style.configure("TSeparator", background=c["border"])
    style.configure("Vertical.TScrollbar", background=c["panel_alt"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["text_dim"])
    style.configure("Horizontal.TScrollbar", background=c["panel_alt"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["text_dim"])
    return c
