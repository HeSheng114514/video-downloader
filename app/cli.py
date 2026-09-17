# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""命令行模式：自检与无界面下载（便于自动化测试与高级用户）。"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import bootstrap, paths
from .config import ConfigStore
from .manager import TaskManager
from .models import TaskState
from .platforms import PLATFORMS, detect_platform, platform_name
from .utils import extract_urls, human_bytes, human_speed


def selftest() -> int:
    """环境自检：不下载任何内容，只验证依赖与解析链路。"""
    print("=" * 62)
    print(f"  {paths.APP_NAME} v{paths.APP_VERSION}  环境自检")
    print("=" * 62)
    ok = True

    print(f"\n[1] Python: {sys.version.split()[0]}  ({sys.executable})")
    try:
        import tkinter

        print(f"    tkinter: OK ({tkinter.TkVersion})")
    except Exception as e:
        ok = False
        print(f"    tkinter: 失败 {e}")

    print("\n[2] 核心模块导入")
    for mod in ("app.config", "app.net", "app.manager", "app.engines.ytdlp",
                "app.engines.douyin", "app.engines.kuaishou", "app.ui.main_window"):
        try:
            __import__(mod)
            print(f"    {mod}: OK")
        except Exception as e:
            ok = False
            print(f"    {mod}: 失败 {type(e).__name__}: {e}")

    print("\n[3] 运行环境")
    cmd = bootstrap.ytdlp_command()
    st = bootstrap.Bootstrap().status()
    ver = st["ytdlp_version"]
    print(f"    yt-dlp : {'OK ' + ver if ver else '未安装'}  后端: {st['ytdlp_backend']}")
    print(f"             命令: {' '.join(cmd) if cmd else '-'}")
    if st.get("ytdlp_exe_broken"):
        print("             注意: bin\\yt-dlp.exe 存在但无法运行（可能被杀软拦截或临时目录受限），"
              "已自动改用其他后端")
    ff = paths.find_ffmpeg()
    print(f"    ffmpeg : {ff if ff else '未安装（高清合并/音频提取需要）'}")
    if ff:
        import subprocess as _sp

        try:
            r = _sp.run([str(ff), "-version"], capture_output=True, encoding="utf-8",
                        errors="replace", timeout=20)
            print(f"             版本: {(r.stdout or '').splitlines()[0][:70]}")
        except Exception:
            pass
    if not cmd:
        ok = False

    print("\n[4] 平台识别")
    samples = [
        "https://www.bilibili.com/video/BV1GJ411x7h7",
        "https://b23.tv/abc123",
        "https://v.douyin.com/sLDScR",
        "https://www.douyin.com/video/6961737553342991651",
        "https://v.kuaishou.com/abcde",
        "https://www.kuaishou.com/short-video/3xabcdef",
        "https://www.tiktok.com/@user/video/123",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.xiaohongshu.com/explore/abc",
    ]
    for s in samples:
        key = detect_platform(s)
        print(f"    {platform_name(key):>8s}  {s}")

    print("\n[5] 分享文案提取")
    text = "7.85 复制打开抖音，看看【某某】的作品 https://v.douyin.com/sLDScR/ 快来看吧！"
    print(f"    提取结果: {extract_urls(text)}")

    print("\n[6] 配置")
    cfg = ConfigStore.get()
    print(f"    配置文件: {paths.config_file()}")
    print(f"    下载目录: {cfg.download_dir}")
    print(f"    画质: {cfg.quality}  并发: {cfg.concurrency}  代理: {cfg.proxy or '未设置'}")

    print("\n" + "=" * 62)
    print("  自检结果：" + ("全部通过 ✔" if ok else "存在问题 ✘（详见上文）"))
    print("=" * 62)
    return 0 if ok else 1


def download_cli(args: argparse.Namespace) -> int:
    cfg = ConfigStore.get()
    if args.out:
        cfg.download_dir = args.out
    if args.quality:
        cfg.quality = args.quality
    if args.cookies_from_browser:
        cfg.cookies_from_browser = args.cookies_from_browser
    if args.cookies:
        cfg.cookies_file = args.cookies
    if args.proxy:
        cfg.proxy = args.proxy
    if args.audio:
        cfg.audio_only = True
    cfg.concurrency = max(1, args.jobs)
    Path(cfg.download_dir).mkdir(parents=True, exist_ok=True)

    urls = list(args.urls)
    for u in list(urls):
        if not u.startswith("http"):
            urls.remove(u)
            urls.extend(extract_urls(u))
    if not urls:
        print("没有可下载的链接")
        return 2

    finished: dict[int, TaskState] = {}

    def on_event(kind: str, payload: dict) -> None:
        task = payload.get("task")
        if kind == "log":
            print(f"  · {payload['message']}")
        elif kind == "task_progress" and task:
            pct = f"{task.progress:5.1f}%"
            print(f"\r  [{task.id}] {pct} {human_speed(task.speed)} "
                  f"{human_bytes(task.downloaded)}/{human_bytes(task.total)}   ", end="", flush=True)
        elif kind == "task_update" and task and task.state.is_finished:
            if finished.get(task.id) != task.state:
                finished[task.id] = task.state
                print()
                print(f"  [{task.id}] {task.state.value}: {task.filepath or task.error}")

    manager = TaskManager(on_event, cfg)
    tasks = manager.add_urls(urls, auto_parse=False)
    manager.enqueue_all("download")

    while True:
        time.sleep(0.5)
        alive = [t for t in manager.tasks if not t.state.is_finished]
        if not alive:
            break
    manager.shutdown()

    done = [t for t in manager.tasks if t.state == TaskState.DONE]
    failed = [t for t in manager.tasks if t.state == TaskState.ERROR]
    print("\n" + "-" * 62)
    print(f"完成 {len(done)} 个，失败 {len(failed)} 个")
    for t in done:
        print(f"  ✔ {t.filepath}")
    for t in failed:
        print(f"  ✘ {t.url}\n     {t.error}")
    return 0 if not failed else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="视频下载器", description="支持抖音/快手/B站/YouTube/TikTok 等站点的视频下载工具")
    p.add_argument("--selftest", action="store_true", help="运行环境自检")
    p.add_argument("--url", dest="urls", nargs="*", help="要下载的链接（命令行模式）")
    p.add_argument("--out", help="保存目录")
    p.add_argument("--quality", help="画质：best/1080/720/480/audio")
    p.add_argument("--audio", action="store_true", help="仅下载音频")
    p.add_argument("--jobs", type=int, default=2, help="并发数")
    p.add_argument("--proxy", help="代理，如 http://127.0.0.1:7890")
    p.add_argument("--cookies", help="cookies.txt 路径")
    p.add_argument("--cookies-from-browser", help="从浏览器读取 Cookie：chrome/edge/firefox")
    p.add_argument("--gui", action="store_true", help="强制启动图形界面")
    return p
