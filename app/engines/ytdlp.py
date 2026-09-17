# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""yt-dlp 引擎：覆盖 YouTube / TikTok / 哔哩哔哩 / 抖音(带 Cookie) 等 1000+ 站点。"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from .. import bootstrap, paths
from .. import cookies as ck
from ..models import MediaInfo
from ..platforms import detect_platform
from ..utils import popen_kwargs
from .base import BaseEngine, CookieError, EngineCancelled, EngineContext, EngineError

RESULT_MARKER = "##FILE##"
PROGRESS_MARKER = "##PROG##"

# 浏览器 Cookie 读取失败的典型特征
#   Chrome / Edge 127+ 起启用 App-Bound 加密，yt-dlp 无法用 DPAPI 解密
#   官方说明：https://github.com/yt-dlp/yt-dlp/issues/10927
DPAPI_MARKERS = ("dpapi", "could not be decrypted", "failed to decrypt")
COOKIE_DB_MARKERS = ("unable to open the cookie database", "cookie database",
                     "could not copy", "failed to open the cookie")
COOKIE_FAIL_HINT = (
    "浏览器 Cookie 读取失败：Chrome / Edge 127+ 启用了 App-Bound 加密，"
    "yt-dlp 无法解密其 Cookie（官方已知限制，无法绕过）。"
    "请在「设置 → 网络与登录 → Cookie 助手」中改用 Firefox，或导出 cookies.txt 后选择该文件"
)


def _is_cookie_failure(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in DPAPI_MARKERS) or any(m in low for m in COOKIE_DB_MARKERS)


def _decode(raw: bytes) -> str:
    """解码 yt-dlp 的输出。

    正常情况下子进程按 UTF-8 输出（引擎已注入 PYTHONIOENCODING）；
    但某些环境（如 exe 忽略该变量）会退回系统 ANSI 代码页，
    此时按 GBK 再试一次，避免中文标题/路径变成乱码。
    """
    if not raw:
        return ""
    try:
        text = raw.decode("utf-8")
        if "\ufffd" not in text:
            return text
    except UnicodeDecodeError:
        pass
    for enc in ("gbk", "cp936", "big5"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def _kill_tree(proc: subprocess.Popen) -> None:
    """终止进程及其子进程（ffmpeg 等）。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, **popen_kwargs())
        else:
            proc.terminate()
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


class YtDlpEngine(BaseEngine):
    key = "ytdlp"
    name = "yt-dlp"

    # ------------------------------------------------------------ 命令构造
    def available(self) -> bool:
        return bootstrap.ytdlp_command() is not None

    def _base_args(self, ctx: EngineContext, use_cookies: bool = True) -> list[str]:
        cfg = ctx.config
        cmd = bootstrap.ytdlp_command()
        if not cmd:
            raise EngineError("未找到 yt-dlp，请先在「设置 → 运行环境」中安装")
        args = list(cmd) + [
            "--ignore-config",
            "--no-color",
            "--newline",
            "--no-warnings",
            "--socket-timeout", "20",
            "--retries", str(max(1, cfg.retries)),
            "--fragment-retries", str(max(1, cfg.retries)),
            "--concurrent-fragments", str(max(1, cfg.concurrent_fragments)),
            "--no-mtime",
            "--windows-filenames",
        ]
        if cfg.insecure:
            args += ["--no-check-certificates"]
        if cfg.proxy.strip():
            args += ["--proxy", cfg.proxy.strip()]
        if cfg.user_agent.strip():
            args += ["--user-agent", cfg.user_agent.strip()]
        if use_cookies:
            args += self._cookie_args(ctx)
        if cfg.speed_limit.strip():
            args += ["--limit-rate", cfg.speed_limit.strip()]
        ff = paths.find_ffmpeg()
        if ff:
            args += ["--ffmpeg-location", str(ff.parent)]
        if not cfg.playlist:
            args += ["--no-playlist"]
        if cfg.playlist_items.strip():
            args += ["--playlist-items", cfg.playlist_items.strip()]
        if cfg.extra_ytdlp_args.strip():
            try:
                args += shlex.split(cfg.extra_ytdlp_args, posix=False)
            except Exception:
                args += cfg.extra_ytdlp_args.split()
        return args

    def _cookie_args(self, ctx: EngineContext) -> list[str]:
        """Cookie 参数，优先级：手动填写 > cookies.txt 文件 > 浏览器读取。

        手动填写的内容会先转成 Netscape 格式的临时 cookies.txt —— 这样与用户
        自己导出的文件完全等价，兼容性最好，也能同时被自研引擎（抖音/快手）复用。
        """
        cfg = ctx.config
        manual = getattr(cfg, "manual_cookies", None) or {}
        if isinstance(manual, dict) and manual:
            path = ck.manual_cookie_file_path(paths.temp_dir())
            try:
                count = ck.write_netscape(path, manual)
            except Exception as e:
                count = 0
                ctx.log(f"⚠ 手动 Cookie 写入失败：{type(e).__name__} {e}")
            if count:
                ctx.log(f"使用手动填写的 Cookie（{len(manual)} 个域名 / {count} 条）")
                return ["--cookies", str(path)]
        if cfg.cookies_file.strip() and Path(cfg.cookies_file).is_file():
            return ["--cookies", cfg.cookies_file.strip()]
        if cfg.cookies_from_browser.strip():
            return ["--cookies-from-browser", cfg.cookies_from_browser.strip()]
        return []

    def _format_args(self, ctx: EngineContext) -> list[str]:
        cfg = ctx.config
        ffmpeg = paths.find_ffmpeg()
        if cfg.audio_only:
            if not ffmpeg:
                raise EngineError("「仅音频」需要 ffmpeg 提取音轨，请在「设置 → 运行环境」中一键安装")
            args = [
                "-f", "ba/b",
                "-x",
                "--audio-format", cfg.audio_format or "mp3",
                "--audio-quality", str(cfg.audio_quality or "0"),
            ]
            if cfg.embed_thumbnail:
                args += ["--embed-thumbnail"]
            if cfg.embed_metadata:
                args += ["--embed-metadata"]
            return args

        if not ffmpeg:
            # 无 ffmpeg：只能下载单文件（渐进式）格式，无法合并分离的音视频流
            m = re.search(r"height<=(\d+)", cfg.format_selector)
            single = f"b[height<={m.group(1)}]/b" if m else "b"
            ctx.log("未检测到 ffmpeg，已改用单文件格式（画质可能偏低）；"
                    "可在「设置 → 运行环境」安装 ffmpeg 后下载高清")
            return ["-f", single]

        args = ["-f", cfg.format_selector]
        if cfg.prefer_mp4:
            args += ["--merge-output-format", "mp4", "--remux-video", "mp4"]
        if cfg.embed_thumbnail:
            args += ["--embed-thumbnail"]
        if cfg.embed_metadata:
            args += ["--embed-metadata"]
        return args

    def _download_args(self, ctx: EngineContext, workdir: Path,
                       use_cookies: bool = True) -> list[str]:
        cfg = ctx.config
        outdir = Path(cfg.download_dir)
        result_file = workdir / "result.txt"
        args = self._base_args(ctx, use_cookies) + self._format_args(ctx) + [
            "-o", str(outdir / (cfg.filename_template or "%(title).120B.%(ext)s")),
            "--no-simulate",
            "--progress",
            "--progress-template", f"download:{PROGRESS_MARKER}%(progress)j",
            "--print-to-file", f"after_move:{RESULT_MARKER}%(filepath)s", str(result_file),
        ]
        if not cfg.keep_original:
            args += ["--force-overwrites"]
        if cfg.write_thumbnail:
            args += ["--write-thumbnail"]
        if cfg.write_subtitles:
            args += ["--write-subs", "--sub-langs", "zh-Hans,zh-CN,zh,en", "--convert-subs", "srt"]
        if cfg.auto_subtitle:
            args += ["--write-auto-subs", "--sub-langs", "zh-Hans,zh-CN,zh,en"]
        if cfg.sponsorblock:
            args += ["--sponsorblock-remove", "sponsor"]
        return args

    # ------------------------------------------------------------ 解析
    def probe(self, url: str, ctx: EngineContext) -> MediaInfo:
        """解析链接。

        若浏览器 Cookie 读取失败（App-Bound 加密），自动去掉 Cookie 重试一次，
        保证公共视频仍能正常解析，而不是整个任务直接失败。
        """
        try:
            return self._probe_once(url, ctx, use_cookies=True)
        except CookieError as e:
            ctx.log(f"⚠ {e}")
            ctx.log("已自动改用「无 Cookie 模式」重新解析（画质可能受限）")
            return self._probe_once(url, ctx, use_cookies=False)

    def _probe_once(self, url: str, ctx: EngineContext, use_cookies: bool = True) -> MediaInfo:
        workdir = paths.make_temp_dir("probe_")
        try:
            args = self._base_args(ctx, use_cookies) + [
                "-J", "--skip-download", "--no-playlist" if not ctx.config.playlist else "--yes-playlist",
            ]
            args.append(url)
            ctx.log("解析：" + url[:110])
            env = bootstrap.extra_env()
            proc = subprocess.run(args, capture_output=True, timeout=180,
                                  env=env, **popen_kwargs())
            out = _decode(proc.stdout or b"").strip()
            err = _decode(proc.stderr or b"")
            if not out:
                if use_cookies and _is_cookie_failure(err):
                    raise CookieError(COOKIE_FAIL_HINT)
                raise EngineError(self._friendly_error(err))
            data = json.loads(out[out.find("{"):]) if out.find("{") >= 0 else {}
            info = self._to_info(url, data)
            if use_cookies and _is_cookie_failure(err):
                # 解析虽然成功（如公共视频），但要提醒用户 Cookie 其实没读进来
                ctx.log("⚠ 浏览器 Cookie 未能读取（App-Bound 加密），本次未使用登录态；"
                        "如需要高清或登录内容，请改用 cookies.txt 或 Firefox")
            self._log_qualities(data, ctx)
            return info
        except subprocess.TimeoutExpired:
            raise EngineError("解析超时，请检查网络或代理设置")
        except json.JSONDecodeError:
            raise EngineError("解析结果异常，可能是站点改版或需要登录")
        finally:
            try:
                import shutil

                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _log_qualities(data: dict, ctx: EngineContext) -> None:
        """把可用画质写进日志，便于判断画质上限（例如未登录 B 站只有 720P）。"""
        formats = data.get("formats") or []
        heights = sorted({int(f["height"]) for f in formats
                          if isinstance(f, dict) and f.get("height")}, reverse=True)
        if not heights:
            entries = data.get("entries") or []
            if entries and isinstance(entries[0], dict):
                heights = sorted({int(f["height"]) for f in (entries[0].get("formats") or [])
                                  if isinstance(f, dict) and f.get("height")}, reverse=True)
        if not heights:
            return
        ctx.log("可用画质：" + " / ".join(f"{h}P" for h in heights[:10])
                + f"（最高 {heights[0]}P）")
        wanted = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720, "480": 480}.get(
            ctx.config.quality or "")
        if wanted and heights[0] < wanted:
            has_cookie = bool(ctx.config.cookies_file.strip()
                              or ctx.config.cookies_from_browser.strip())
            hint = ("" if has_cookie else "；该视频可能需要登录才能解锁更高画质，"
                                          "可在「设置 → 网络与登录 → Cookie 助手」配置 Cookie 后重试")
            ctx.log(f"ℹ 你选择的画质为 {wanted}P，但此视频最高只有 {heights[0]}P{hint}")

    @staticmethod
    def _to_info(url: str, data: dict) -> MediaInfo:
        platform = detect_platform(url)
        # 通用解析器（Generic）常把普通网页当成视频，需要识别并拒绝，
        # 否则会出现「标题就是链接」的假成功。
        extractor = str(data.get("extractor_key") or data.get("extractor") or "")
        formats = data.get("formats") or []
        entries = data.get("entries") or []
        if extractor.lower() == "generic" or data.get("_type") == "url":
            if not formats and not entries:
                raise EngineError("该链接不是可直接下载的媒体页面（通用解析未找到视频）")

        info = MediaInfo(url=url, platform=platform)
        info.title = data.get("title") or data.get("id") or url
        info.uploader = data.get("uploader") or data.get("channel") or data.get("creator") or ""
        info.duration = float(data.get("duration") or 0)
        info.thumbnail = data.get("thumbnail") or ""
        info.webpage_url = data.get("webpage_url") or url
        info.ext = data.get("ext") or "mp4"
        info.filesize = int(data.get("filesize") or data.get("filesize_approx") or 0)
        if data.get("_type") == "playlist":
            info.is_playlist = True
            info.playlist_count = len(entries) or int(data.get("playlist_count") or 1)
            if entries:
                first = entries[0] or {}
                info.title = f"{info.title}（共 {info.playlist_count} 个视频）"
                info.thumbnail = info.thumbnail or first.get("thumbnail") or ""
        # 兜底校验：标题与链接相同且时长/封面都没有 → 视为解析失败
        if info.title.strip() == url.strip() and not info.duration and not info.thumbnail \
                and not info.is_playlist:
            raise EngineError("未能从该链接解析出有效视频信息")
        return info

    @staticmethod
    def _friendly_error(text: str) -> str:
        t = (text or "").strip().splitlines()
        msg = t[-1] if t else "未知错误"
        if _is_cookie_failure(text):
            return COOKIE_FAIL_HINT
        if "Fresh cookies" in text or "cookies" in text.lower() and "needed" in text.lower():
            return "需要登录 Cookie：请在「设置 → 网络与登录 → Cookie 助手」中配置（抖音/B站高清必需）"
        if "Sign in to confirm" in text:
            return "YouTube 要求登录验证：请配置代理或导入 Cookie"
        if "Unable to download webpage" in text or "Connection" in text:
            return "网络连接失败：YouTube/TikTok 等站点通常需要配置代理"
        if "Unsupported URL" in text:
            return "该链接暂不受支持"
        if "Private video" in text:
            return "该视频为私密视频，无法下载"
        if "ffmpeg" in text.lower():
            return "需要 ffmpeg：请在「设置 → 运行环境」中一键安装"
        return msg[:200]

    # ------------------------------------------------------------ 下载
    def download(self, url: str, info: MediaInfo, ctx: EngineContext) -> Path:
        """下载视频。

        若浏览器 Cookie 读取失败，自动去掉 Cookie 重试，避免整个任务失败。
        """
        try:
            return self._download_once(url, info, ctx, use_cookies=True)
        except CookieError as e:
            ctx.log(f"⚠ {e}")
            ctx.log("已自动改用「无 Cookie 模式」重新下载（画质可能受限）")
            ctx.on_status("下载中（无 Cookie）")
            return self._download_once(url, info, ctx, use_cookies=False)

    def _download_once(self, url: str, info: MediaInfo, ctx: EngineContext,
                       use_cookies: bool = True) -> Path:
        workdir = paths.make_temp_dir("dl_")
        result_file = workdir / "result.txt"
        args = self._download_args(ctx, workdir, use_cookies)
        args.append(url)

        env = bootstrap.extra_env()
        ctx.log("开始下载：" + (info.title or url)[:80])
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            **popen_kwargs(),
        )
        ctx.on_proc(proc)
        ctx.on_status("下载中")
        last_err: list[str] = []
        tail: list[str] = []          # 保留全部输出尾部，用于识别 Cookie 解密失败
        try:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                if ctx.cancelled():
                    _kill_tree(proc)
                    raise EngineCancelled("任务已取消")
                line = _decode(raw).rstrip()
                if not line:
                    continue
                tail.append(line)
                if len(tail) > 120:
                    del tail[:60]
                self._handle_line(line, ctx, last_err)
            proc.wait()
        finally:
            if proc.poll() is None:
                _kill_tree(proc)
            try:
                proc.stdout.close()  # type: ignore[union-attr]
            except Exception:
                pass
            time.sleep(0.2)

        if ctx.cancelled():
            raise EngineCancelled("任务已取消")

        cookie_failed = use_cookies and _is_cookie_failure("\n".join(tail))

        # 结果文件优先（UTF-8 写入，避免控制台编码问题）
        final: Path | None = None
        try:
            if result_file.is_file():
                for line in result_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith(RESULT_MARKER):
                        final = Path(line[len(RESULT_MARKER):].strip())
        except Exception:
            pass
        if final and final.exists():
            if cookie_failed:
                ctx.log("⚠ 浏览器 Cookie 未能读取（App-Bound 加密），本次未使用登录态；"
                        "画质可能受限，建议改用 cookies.txt 或 Firefox")
            ctx.on_file(str(final))
            return final
        if proc.returncode != 0:
            combined = "\n".join(last_err[-6:]) or "\n".join(tail[-6:])
            if cookie_failed:
                raise CookieError(COOKIE_FAIL_HINT)
            raise EngineError(self._friendly_error(combined) or "下载失败")
        found = self._guess_output(info, ctx)
        if found:
            ctx.on_file(str(found))
            return found
        raise EngineError("下载已完成，但未能定位输出文件")

    def _handle_line(self, line: str, ctx: EngineContext, last_err: list[str]) -> None:
        if line.startswith(PROGRESS_MARKER):
            payload = line[len(PROGRESS_MARKER):]
            try:
                d = json.loads(payload)
            except Exception:
                return
            status = d.get("status")
            if status == "finished":
                ctx.on_progress(int(d.get("downloaded_bytes") or 0),
                                int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0), 0.0)
                ctx.on_status("处理中")
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0.0
            ctx.on_progress(int(got), int(total), float(speed))
            return
        if line.startswith("[download] Destination:") or line.startswith("[Merger]") \
                or line.startswith("[ExtractAudio] Destination:"):
            ctx.log(line[:160])
            return
        if "ERROR:" in line:
            last_err.append(line)
            ctx.log(line[:200])
            return
        if line.startswith("["):
            return
        if line.strip():
            ctx.log(line[:180])

    @staticmethod
    def _guess_output(info: MediaInfo, ctx: EngineContext) -> Path | None:
        """兜底：在下载目录里找最近修改的媒体文件。"""
        outdir = Path(ctx.config.download_dir)
        if not outdir.is_dir():
            return None
        exts = {".mp4", ".mkv", ".webm", ".flv", ".mov", ".mp3", ".m4a", ".flac", ".wav", ".aac", ".opus"}
        newest: tuple[float, Path] | None = None
        for p in outdir.rglob("*"):
            if p.suffix.lower() in exts and p.is_file():
                mtime = p.stat().st_mtime
                if time.time() - mtime < 6 * 3600 and (newest is None or mtime > newest[0]):
                    newest = (mtime, p)
        return newest[1] if newest else None
