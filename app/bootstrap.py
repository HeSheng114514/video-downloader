# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""依赖自举：自动获取 yt-dlp 与 ffmpeg。

设计要点
* 多镜像顺序重试（GitHub 直连 → 加速代理 → 国内镜像 → PyPI 镜像）
* 断点续传，弱网也能装完
* 全程进度回调，GUI 中可视化
"""
from __future__ import annotations

import gzip
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

from . import paths
from .net import HttpClient, HttpError, SourceTooSlow
from .utils import popen_kwargs

ProgressCB = Callable[[str, int, int], None]   # (阶段描述, 已下载, 总大小)

YTDLP_SOURCES = [
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "https://gh-proxy.com/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "https://ghfast.top/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "https://ghproxy.net/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "https://hub.gitmirror.com/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "https://gh.llkk.cc/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
]

PIP_MIRRORS = [
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://mirrors.cloud.tencent.com/pypi/simple/",
    "https://mirrors.ustc.edu.cn/pypi/simple/",
    "https://pypi.org/simple/",
]

FFMPEG_SOURCES = [
    # 官方完整构建（ffmpeg + ffprobe，版本最新）
    ("gyan", "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"),
    ("btbn", "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
    ("btbn-proxy", "https://ghfast.top/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
    ("btbn-proxy2", "https://gh-proxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
    # 精简版（含 ffmpeg + ffprobe，来自 npmmirror 的 npm 包）
    ("npm-mini", "https://registry.npmmirror.com/@ffmpeg-installer/win32-x64/-/win32-x64-4.1.0.tgz"),
    ("npm-mini2", "https://registry.npmjs.org/@ffmpeg-installer/win32-x64/-/win32-x64-4.1.0.tgz"),
]

# 单文件直链源（.gz 压缩的裸二进制），国内镜像速度极快，优先使用
FFMPEG_DIRECT_SOURCES = [
    ("npmmirror", "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/ffmpeg-win32-x64.gz", "ffmpeg.exe"),
    ("npmmirror", "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/ffprobe-win32-x64.gz", "ffprobe.exe"),
]

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _download_with_fallback(
    sources: list[str] | list[tuple[str, str]],
    dst: Path,
    log: Callable[[str], None] | None = None,
    progress: ProgressCB | None = None,
    proxy: str = "",
    insecure: bool = False,
    min_ok: int = 100_000,
) -> str | None:
    """依次尝试多个镜像下载到 dst，返回成功的源标识。

    采用分块下载（固定大小 Range 请求），在长连接被中断的网络环境下更稳。
    """
    client = HttpClient(proxy=proxy, insecure=insecure, timeout=40, retries=1)
    for item in sources:
        if isinstance(item, tuple):
            name, url = item
        else:
            name, url = "src", item
        if log:
            log(f"尝试下载源：{name}")
        for attempt in range(1, 4):
            try:
                started = time.time()

                def _cb(done: int, total: int, speed: float, _u=url) -> None:
                    if progress:
                        progress(_u, done, total)
                    # 慢源守护：45 秒内不到 1.5MB 视为不可用，自动换源
                    if time.time() - started > 45 and done < 1_500_000:
                        raise SourceTooSlow(f"速度过慢（{done // 1024} KB / 45s）")

                client.download(url, dst, on_progress=_cb, chunked=True, max_retries=4)
                size = dst.stat().st_size if dst.exists() else 0
                if size < min_ok:
                    if log:
                        log(f"源 {name} 数据过小（{size} 字节），换源")
                    break
                if log:
                    log(f"下载完成：{dst.name}（{size / 1048576:.1f} MB，来源 {name}）")
                return name
            except SourceTooSlow as e:
                if log:
                    log(f"源 {name} {e}，自动切换其他镜像")
                break
            except Exception as e:
                if log:
                    log(f"源 {name} 第 {attempt} 次失败：{type(e).__name__} {str(e)[:110]}")
                if "已取消" in str(e):
                    raise
                time.sleep(1.0 * attempt)
        # 换源前清掉残留分片，避免脏数据
        try:
            part = dst.with_suffix(dst.suffix + ".part")
            if part.exists():
                part.unlink()
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
    return None


# ------------------------------------------------------------------ yt-dlp

def ytdlp_module_available() -> bool:
    """源码模式下当前解释器是否能 import yt_dlp（含 vendor 目录）。"""
    if paths.is_frozen():
        return False
    _vendor_on_path()
    try:
        import yt_dlp  # noqa: F401

        return True
    except Exception:
        return False


def ytdlp_module_command() -> list[str] | None:
    """模块后端的命令前缀；不可用时返回 None。

    * 源码模式：python -m yt_dlp
    * EXE 模式：自身进程 + --ytdlp 通道（需要 vendor\\yt_dlp 随包发布）
    """
    if paths.is_frozen():
        return [sys.executable, "--ytdlp"] if _frozen_module_ok() else None
    if ytdlp_module_available():
        return [sys.executable, "-m", "yt_dlp"]
    return None


def _frozen_module_ok() -> bool:
    """EXE 模式下检测 yt-dlp 模块通道是否真的可用。

    yt-dlp 可能随包内置（PyInstaller 打进 exe），也可能放在 exe 同级的 vendor 目录，
    这里直接用自身进程跑一次 --version 来验证，不依赖目录是否存在。
    """
    key = "__frozen_module__"
    if key in _exe_check_cache:
        return _exe_check_cache[key]
    ok = False
    try:
        r = subprocess.run([sys.executable, "--ytdlp", "--version"], capture_output=True,
                           timeout=150, encoding="utf-8", errors="replace",
                           env=extra_env(), **popen_kwargs())
        ok = r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        ok = False
    _exe_check_cache[key] = ok
    return ok


def _vendor_on_path() -> None:
    vendor = paths.app_root() / "vendor"
    if vendor.is_dir():
        p = str(vendor)
        if p not in sys.path:
            sys.path.insert(0, p)


def ytdlp_command() -> list[str] | None:
    """返回可用的 yt-dlp 命令前缀。

    优先级：bin/yt-dlp.exe（需通过 --version 校验）→ PATH 中的 yt-dlp → Python 模块方式。
    被截断/损坏的 exe 会被自动忽略并删除，避免反复失败。
    """
    exe = paths.ytdlp_path()
    if exe.is_file():
        if _exe_works(exe):
            return [str(exe)]
        # 注意：不删除文件。某些环境（杀软拦截、临时目录受限）会让 exe 暂时无法运行，
        # 但它在正常环境下是可用的，删掉会白白浪费一次 17MB 下载。
    which = shutil.which("yt-dlp")
    if which and _exe_works(Path(which)):
        return [which]
    module_cmd = ytdlp_module_command()
    if module_cmd:
        return module_cmd
    return None


def ytdlp_exe_broken() -> bool:
    """bin 目录下的 exe 存在但无法运行。"""
    exe = paths.ytdlp_path()
    return exe.is_file() and not _exe_works(exe)


_exe_check_cache: dict[str, bool] = {}


def _exe_works(exe: Path) -> bool:
    """校验可执行文件是否真的能用（结果缓存）。"""
    key = str(exe)
    if key in _exe_check_cache:
        return _exe_check_cache[key]
    if not exe.is_file() or exe.stat().st_size < 1_000_000:
        _exe_check_cache[key] = False
        return False
    ok = False
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, timeout=90,
                           encoding="utf-8", errors="replace", **popen_kwargs())
        ok = r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        ok = False
    _exe_check_cache[key] = ok
    return ok


def invalidate_cache() -> None:
    _exe_check_cache.clear()


def extra_env() -> dict:
    """构造子进程环境变量。

    关键：以 `python -m yt_dlp` 模块方式运行时，必须把 vendor 目录
    通过 PYTHONPATH 传给子进程，否则子进程找不到 yt_dlp 模块。
    """
    env = dict(os.environ)
    vendor = paths.app_root() / "vendor"
    if vendor.is_dir():
        parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
        if str(vendor) not in parts:
            parts.insert(0, str(vendor))
        env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def ytdlp_version(cmd: list[str] | None = None) -> str:
    cmd = cmd or ytdlp_command()
    if not cmd:
        return ""
    try:
        r = subprocess.run(cmd + ["--version"], capture_output=True, timeout=60,
                           encoding="utf-8", errors="replace", env=extra_env(), **popen_kwargs())
        return (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    except Exception:
        return ""


def install_ytdlp(
    log: Callable[[str], None] | None = None,
    progress: ProgressCB | None = None,
    proxy: str = "",
    insecure: bool = False,
) -> bool:
    """下载 yt-dlp.exe；失败则退回 pip 镜像安装 Python 模块。"""
    dst = paths.ytdlp_path()
    ok = _download_with_fallback(YTDLP_SOURCES, dst, log=log, progress=progress,
                                 proxy=proxy, insecure=insecure, min_ok=5_000_000)
    if ok:
        return verify_ytdlp(dst, log)
    if log:
        log("所有 yt-dlp 直链镜像均失败，尝试通过 PyPI 镜像安装 Python 模块…")
    return pip_install_ytdlp(log)


def pip_install_ytdlp(log: Callable[[str], None] | None = None) -> bool:
    if paths.is_frozen():
        # 打包后没有独立的 Python 解释器，无法用 pip 安装模块
        if log:
            log("当前为 EXE 运行模式，无法使用 pip 安装模块；请联网后重试下载 yt-dlp.exe")
        return False
    vendor = paths.app_root() / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    for mirror in PIP_MIRRORS:
        if log:
            log(f"pip 安装 yt-dlp：{mirror}")
        cmd = [
            sys.executable, "-m", "pip", "install", "--target", str(vendor),
            "--upgrade", "--no-cache-dir", "--disable-pip-version-check",
            "-i", mirror, "yt-dlp",
        ]
        if "aliyun" in mirror or "tuna" in mirror or "ustc" in mirror or "tencent" in mirror:
            host = mirror.split("//", 1)[1].split("/", 1)[0]
            cmd += ["--trusted-host", host]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=600,
                               encoding="utf-8", errors="replace", **popen_kwargs())
            if r.returncode == 0 and ytdlp_module_available():
                if log:
                    log("yt-dlp 模块安装成功")
                return True
            if log:
                tail = (r.stderr or r.stdout or "").strip().splitlines()
                log("pip 失败：" + (tail[-1] if tail else str(r.returncode)))
        except Exception as e:
            if log:
                log(f"pip 异常：{e}")
    return False


def verify_ytdlp(exe: Path | None = None, log: Callable[[str], None] | None = None) -> bool:
    exe = exe or paths.ytdlp_path()
    if not exe.is_file():
        return False
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, timeout=60,
                           encoding="utf-8", errors="replace", **popen_kwargs())
        ver = (r.stdout or "").strip()
        if r.returncode == 0 and ver:
            if log:
                log(f"yt-dlp 就绪：{ver}")
            return True
        if log:
            log(f"yt-dlp 校验失败：{(r.stderr or '')[:150]}")
    except Exception as e:
        if log:
            log(f"yt-dlp 校验异常：{e}")
    return False


def update_ytdlp(log: Callable[[str], None] | None = None,
                 progress: ProgressCB | None = None,
                 proxy: str = "", insecure: bool = False) -> bool:
    """更新 yt-dlp：优先官方 -U，失败则整包重下。"""
    cmd = ytdlp_command()
    if not cmd:
        return install_ytdlp(log, progress, proxy, insecure)
    if paths.is_frozen() and "--ytdlp" in cmd:
        # 使用随包模块时无法自行更新，避免误覆盖可用的 exe
        if log:
            log("当前使用随包内置 yt-dlp 模块，如需更新请下载新版程序")
        return True
    if paths.ytdlp_path().is_file():
        try:
            r = subprocess.run(cmd + ["-U"], capture_output=True, timeout=180,
                               encoding="utf-8", errors="replace",
                               env=extra_env(), **popen_kwargs())
            out = (r.stdout or "") + (r.stderr or "")
            if "Updated yt-dlp to" in out or "yt-dlp is up to date" in out:
                if log:
                    log(out.strip().splitlines()[-1])
                return True
        except Exception:
            pass
    return install_ytdlp(log, progress, proxy, insecure)


# ------------------------------------------------------------------ ffmpeg

def _extract_media_tools(archive: Path, dst_dir: Path, log: Callable[[str], None] | None = None) -> bool:
    """从 zip / tar.gz 中提取 ffmpeg.exe / ffprobe.exe 到 dst_dir。"""
    dst_dir.mkdir(parents=True, exist_ok=True)
    wanted = {"ffmpeg.exe", "ffprobe.exe"}
    found: set[str] = set()
    name = archive.name.lower()

    def _handle(inner_name: str, reader) -> None:
        base = Path(inner_name).name
        if base in wanted:
            target = dst_dir / base
            with open(target, "wb") as out:
                shutil.copyfileobj(reader, out)
            found.add(base)

    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if Path(info.filename).name in wanted:
                    with zf.open(info) as fp:
                        _handle(info.filename, fp)
    else:  # tar.gz / tgz
        with tarfile.open(archive, "r:*") as tf:
            for member in tf.getmembers():
                if Path(member.name).name in wanted and member.isfile():
                    fp = tf.extractfile(member)
                    if fp:
                        with fp:
                            _handle(member.name, fp)

    if found and log:
        log("已提取：" + "、".join(sorted(found)))
    return "ffmpeg.exe" in found


def _install_direct_binary(
    name: str,
    url: str,
    target: str,
    log: Callable[[str], None] | None = None,
    progress: ProgressCB | None = None,
    proxy: str = "",
    insecure: bool = False,
) -> bool:
    """下载 .gz 裸二进制并解压到 bin 目录。"""
    dst = paths.bin_dir() / target
    tmp = paths.temp_dir() / f"{name}_{target}.gz"
    ok = _download_with_fallback([(name, url)], tmp, log=log, progress=progress,
                                 proxy=proxy, insecure=insecure, min_ok=3_000_000)
    if not ok:
        return False
    try:
        if log:
            log(f"正在解压 {target}…")
        with gzip.open(tmp, "rb") as src, open(dst, "wb") as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
        return dst.stat().st_size > 1_000_000
    except Exception as e:
        if log:
            log(f"解压 {target} 失败：{type(e).__name__} {str(e)[:100]}")
        return False
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


def install_ffmpeg(
    log: Callable[[str], None] | None = None,
    progress: ProgressCB | None = None,
    proxy: str = "",
    insecure: bool = False,
) -> bool:
    if paths.ffmpeg_path().is_file():
        return True

    # 1) 国内镜像裸二进制（最快，含 ffmpeg + ffprobe）
    if log:
        log("优先尝试国内镜像（npmmirror，速度最快）")
    got_ffmpeg = False
    for name, url, target in FFMPEG_DIRECT_SOURCES:
        if target == "ffmpeg.exe" and got_ffmpeg:
            continue
        if (paths.bin_dir() / target).is_file():
            continue
        if _install_direct_binary(name, url, target, log, progress, proxy, insecure):
            if target == "ffmpeg.exe":
                got_ffmpeg = True
            if log:
                log(f"{target} 安装成功")
    if got_ffmpeg:
        return True

    # 2) 压缩包源兜底
    if log:
        log("镜像直链失败，改用压缩包源")
    tmpdir = paths.make_temp_dir("ffmpeg_")
    try:
        for name, url in FFMPEG_SOURCES:
            suffix = ".tgz" if url.endswith(".tgz") else ".zip"
            archive = tmpdir / f"{name}{suffix}"
            ok = _download_with_fallback([(name, url)], archive, log=log, progress=progress,
                                         proxy=proxy, insecure=insecure, min_ok=5_000_000)
            if not ok:
                continue
            try:
                if _extract_media_tools(archive, paths.bin_dir(), log):
                    return True
            except Exception as e:
                if log:
                    log(f"解压失败：{type(e).__name__} {str(e)[:100]}")
            finally:
                try:
                    archive.unlink()
                except Exception:
                    pass
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return False


def check_ffmpeg(log: Callable[[str], None] | None = None) -> bool:
    exe = paths.find_ffmpeg()
    if not exe:
        return False
    try:
        r = subprocess.run([str(exe), "-version"], capture_output=True, timeout=30,
                           encoding="utf-8", errors="replace", **popen_kwargs())
        if r.returncode == 0:
            if log:
                first = (r.stdout or "").splitlines()[0] if r.stdout else "ffmpeg"
                log(f"ffmpeg 就绪：{first[:60]}")
            return True
    except Exception:
        pass
    return False


# ------------------------------------------------------------------ 组合

class Bootstrap:
    """首次运行时在后台准备运行环境。"""

    def __init__(self, log: Callable[[str], None] | None = None,
                 progress: ProgressCB | None = None, proxy: str = "", insecure: bool = False):
        self.log = log or (lambda m: None)
        self.progress = progress
        self.proxy = proxy
        self.insecure = insecure

    def status(self) -> dict:
        cmd = ytdlp_command()
        backend = "未安装"
        if cmd:
            if cmd[0].endswith("yt-dlp.exe") or cmd[0].endswith("yt-dlp"):
                backend = "yt-dlp.exe"
            else:
                backend = "Python 模块"
        return {
            "ytdlp": bool(cmd),
            "ytdlp_backend": backend,
            "ytdlp_version": ytdlp_version(cmd) if cmd else "",
            "ytdlp_exe_broken": ytdlp_exe_broken(),
            "ffmpeg": bool(paths.find_ffmpeg()),
        }

    def ensure_all(self, need_ffmpeg: bool = True) -> bool:
        ok = True
        if not ytdlp_command():
            ok = install_ytdlp(self.log, self.progress, self.proxy, self.insecure) and ok
        if need_ffmpeg and not paths.find_ffmpeg():
            ok = install_ffmpeg(self.log, self.progress, self.proxy, self.insecure) and ok
        return ok
