# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""程序入口：图形界面 / 命令行 / 自检。"""
from __future__ import annotations

import os
import sys
import traceback


def _fix_windows_dpi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _log_crash(text: str) -> None:
    """把启动异常写入 logs 目录，便于无控制台启动时排查。"""
    try:
        from . import paths

        path = paths.log_dir() / "error.log"
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n===== {__import__('time').strftime('%Y-%m-%d %H:%M:%S')} =====\n{text}\n")
    except Exception:
        pass


def run_gui() -> int:
    _fix_windows_dpi()
    from tkinter import messagebox

    from .ui.main_window import MainWindow

    try:
        app = MainWindow()
    except Exception:
        tb = traceback.format_exc()
        _log_crash(tb)
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("启动失败", tb[-1500:])
            root.destroy()
        except Exception:
            print(tb, file=sys.stderr)
        return 1
    app.mainloop()
    return 0


def run_ytdlp_module(args: list[str]) -> int:
    """以「自身进程 + 内置 yt-dlp 模块」运行 yt-dlp 命令行。

    打包成 EXE 后没有独立的 Python 解释器，若 bin\\yt-dlp.exe 被杀软拦截，
    可以退回这条通道：程序随包的 vendor\\yt_dlp 模块直接执行。
    用法（由引擎内部调用）：VideoDownloader.exe --ytdlp <yt-dlp 参数...>
    """
    from . import paths

    vendor = paths.app_root() / "vendor"
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    try:
        from yt_dlp import main as ytdlp_main
    except Exception as e:
        print(f"ERROR: 无法加载内置 yt-dlp 模块（{type(e).__name__}: {e}）", file=sys.stderr)
        return 1
    sys.argv = ["yt-dlp", *args]
    try:
        ytdlp_main(sys.argv)
        return 0
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # yt-dlp 模块通道（必须在 argparse 之前处理）
    if argv and argv[0] == "--ytdlp":
        return run_ytdlp_module(argv[1:])

    from .cli import build_parser, download_cli, selftest

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.urls and not args.gui:
        return download_cli(args)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
