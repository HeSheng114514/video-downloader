# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#!/usr/bin/env python3
"""视频下载器 —— 启动入口。

用法：
    python run.py                     启动图形界面
    python run.py --selftest          环境自检
    python run.py --url <链接> --out <目录>   命令行下载
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# 让内置依赖（vendor 目录）可用：yt-dlp 也可作为 Python 模块运行
VENDOR = BASE / "vendor"
if VENDOR.is_dir() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

# 保证中文输出不因控制台编码而报错
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
