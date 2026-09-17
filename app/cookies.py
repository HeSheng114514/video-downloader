# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 视频下载器 contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
"""浏览器 Cookie 获取辅助。

背景
----
Chrome / Edge 自 127 版起在 Windows 上启用了 **App-Bound 加密**：Cookie 的
解密密钥被浏览器进程独占保护，任何外部程序（包含 yt-dlp）都无法用 DPAPI 解开，
于是出现::

    ERROR: Failed to decrypt with DPAPI

这是浏览器侧的安全机制，yt-dlp 官方明确表示无法绕过
（见 https://github.com/yt-dlp/yt-dlp/issues/10927 ，master 分支亦无相关实现）。

可行途径只有两条：

1. **Firefox**：其 cookies.sqlite 未使用该加密，`--cookies-from-browser firefox` 可正常读取
2. **cookies.txt**：用浏览器扩展导出 Netscape 格式 Cookie 文件，再通过 `--cookies` 使用

本模块负责：检测可用浏览器、解析与校验 cookies.txt、生成请求头。
"""
from __future__ import annotations

import configparser
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Chrome/Edge 系（受 App-Bound 加密影响）
CHROMIUM_BROWSERS = ("chrome", "edge", "brave", "chromium", "opera", "vivaldi")
# 不受影响的浏览器
SAFE_BROWSERS = ("firefox", "safari")

BROWSER_LABELS = {
    "chrome": "Google Chrome", "edge": "Microsoft Edge", "firefox": "Firefox",
    "brave": "Brave", "chromium": "Chromium", "opera": "Opera", "vivaldi": "Vivaldi",
}


@dataclass
class CookieFileInfo:
    path: str = ""
    exists: bool = False
    total: int = 0
    domains: Counter = field(default_factory=Counter)
    names: set = field(default_factory=set)
    session_count: int = 0
    error: str = ""

    def domain_list(self, limit: int = 12) -> list[str]:
        return [d for d, _ in self.domains.most_common(limit)]


# 各站点达成「登录态」所需的关键 Cookie
EXPECTED_COOKIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "bilibili": (("bilibili.com",), ("SESSDATA", "bili_jct", "DedeUserID")),
    "douyin": (("douyin.com",), ("ttwid", "sessionid", "passport_csrf_token", "odin_tt", "msToken")),
    "kuaishou": (("kuaishou.com",), ("did", "kuaishou.server.web_st", "kuaishou.server.web_ph")),
    "youtube": (("youtube.com", "google.com"), ("SID", "SAPISID", "__Secure-1PSID", "LOGIN_INFO")),
    "tiktok": (("tiktok.com",), ("sessionid", "sessionid_ss", "ttwid")),
    "xiaohongshu": (("xiaohongshu.com",), ("web_session", "a1", "webId")),
    "weibo": (("weibo.com", "weibo.cn"), ("SUB", "SUBP")),
    "twitter": (("twitter.com", "x.com"), ("auth_token", "ct0")),
}


# ------------------------------------------------------------------ 浏览器检测

def _exe_candidates(browser: str) -> list[Path]:
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    table = {
        "edge": [pf86 / r"Microsoft\Edge\Application\msedge.exe",
                 pf / r"Microsoft\Edge\Application\msedge.exe"],
        "chrome": [pf / r"Google\Chrome\Application\chrome.exe",
                   pf86 / r"Google\Chrome\Application\chrome.exe",
                   local / r"Google\Chrome\Application\chrome.exe"],
        "firefox": [pf / r"Mozilla Firefox\firefox.exe",
                    pf86 / r"Mozilla Firefox\firefox.exe"],
        "brave": [pf / r"BraveSoftware\Brave-Browser\Application\brave.exe"],
    }
    return table.get(browser, [])


def browser_installed(browser: str) -> bool:
    return any(p.is_file() for p in _exe_candidates(browser))


def installed_browsers() -> list[str]:
    return [b for b in ("edge", "chrome", "firefox", "brave") if browser_installed(b)]


def browser_profile_dirs(browser: str) -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    table = {
        "edge": [local / r"Microsoft\Edge\User Data"],
        "chrome": [local / r"Google\Chrome\User Data"],
        "brave": [local / r"BraveSoftware\Brave-Browser\User Data"],
        "firefox": [roaming / r"Mozilla\Firefox"],
    }
    return [p for p in table.get(browser, []) if p.is_dir()]


# ------------------------------------------------------------------ Firefox

def find_firefox_profiles() -> list[dict]:
    """列出 Firefox 配置文件（含 cookies.sqlite 路径）。"""
    base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    profiles: list[dict] = []
    ini = base / "profiles.ini"
    names: dict[str, str] = {}
    if ini.is_file():
        cp = configparser.ConfigParser()
        try:
            cp.read(ini, encoding="utf-8")
        except Exception:
            pass
        for section in cp.sections():
            if not section.lower().startswith("profile"):
                continue
            path = cp.get(section, "Path", fallback="")
            if path:
                names[section] = path
                is_default = cp.get(section, "Default", fallback="0") == "1"
                is_relative = cp.get(section, "IsRelative", fallback="1") == "1"
                cookie = (base / path if is_relative else Path(path)) / "cookies.sqlite"
                profiles.append({"name": section, "path": str(cookie.parent),
                                 "cookies": str(cookie), "default": is_default,
                                 "exists": cookie.is_file()})
    if not profiles:
        pdir = base / "Profiles"
        if pdir.is_dir():
            for d in pdir.iterdir():
                cookie = d / "cookies.sqlite"
                if cookie.is_file():
                    profiles.append({"name": d.name, "path": str(d), "cookies": str(cookie),
                                     "default": False, "exists": True})
    profiles.sort(key=lambda x: (not x["default"], not x["exists"]))
    return profiles


def firefox_cookie_available() -> bool:
    return any(p["exists"] for p in find_firefox_profiles())


# ------------------------------------------------------------------ cookies.txt

def parse_cookies_txt(path: str | Path) -> CookieFileInfo:
    """解析 Netscape 格式 cookies.txt（同时兼容 #HttpOnly_ 前缀行）。"""
    p = Path(path or "")
    info = CookieFileInfo(path=str(p))
    if not p.is_file():
        info.error = "文件不存在"
        return info
    info.exists = True
    now = time.time()
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        info.error = f"无法读取：{e}"
        return info
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        if raw.startswith("#HttpOnly_"):
            raw = raw[len("#HttpOnly_"):]
        elif raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 7:
            parts = re.split(r"\s+", raw, maxsplit=6)
            if len(parts) < 7:
                continue
        domain, _flag, _path, secure, expires, name, _value = parts[:7]
        domain = domain.lstrip(".").lower()
        if not domain or not name:
            continue
        info.total += 1
        info.domains[domain] += 1
        info.names.add(name)
        try:
            if expires and int(expires) > 0 and int(expires) < now:
                continue
        except ValueError:
            pass
        info.session_count += 1
    if info.total == 0:
        info.error = "未解析到任何 Cookie（请确认导出的是 Netscape 格式）"
    return info


def check_cookies_for_platform(path: str | Path, platform_key: str) -> tuple[bool, str, CookieFileInfo]:
    """校验 cookies.txt 是否覆盖指定站点所需的登录 Cookie。"""
    info = parse_cookies_txt(path)
    if not info.exists:
        return False, f"Cookie 文件不存在：{path}", info
    if info.total == 0:
        return False, info.error or "Cookie 文件为空", info
    spec = EXPECTED_COOKIES.get(platform_key)
    if not spec:
        return True, f"已加载 {info.total} 条 Cookie（{len(info.domains)} 个域名）", info
    doms, keys = spec
    hit_domain = any(any(d == dom or d.endswith("." + dom) for dom in doms) for d in info.domains)
    hit_keys = sorted(info.names & set(keys))
    if hit_domain and hit_keys:
        return True, f"已包含 {platform_key} 登录 Cookie（{'、'.join(hit_keys[:3])}）", info
    if hit_domain:
        need = "、".join(keys[:3])
        return False, (f"文件里有 {platform_key} 的域名，但缺少关键 Cookie（需要 {need} 之一）；"
                       f"导出时请确认已登录该站点并选择「导出全部 Cookie」"), info
    return False, (f"文件中没有 {platform_key} 相关域名"
                   f"（当前包含：{'、'.join(info.domain_list(5)) or '无'}）"), info


def read_cookie_header(cookies_file: str, domain_hint: str = "") -> str:
    """把 cookies.txt 转成 Cookie 请求头（可限定域名）。"""
    path = Path(cookies_file or "")
    if not path.is_file():
        return ""
    pairs: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line or line.startswith("#") and not line.startswith("#HttpOnly_"):
                continue
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, _f, _p, _s, _e, name, value = parts[:7]
            if domain_hint and domain_hint not in domain:
                continue
            pairs.append(f"{name}={value}")
    except Exception:
        return ""
    return "; ".join(pairs)


# ------------------------------------------------------------------ 环境诊断

def appbound_risk() -> tuple[bool, str]:
    """判断 Chromium 系浏览器是否可能触发 App-Bound 加密导致的读取失败。"""
    if os.name != "nt":
        return False, ""
    risky = [b for b in CHROMIUM_BROWSERS if browser_installed(b)]
    if not risky:
        return False, ""
    labels = "、".join(BROWSER_LABELS.get(b, b) for b in risky)
    return True, (f"{labels} 自 127 版起启用了 App-Bound 加密，"
                  f"yt-dlp 无法解密其 Cookie（官方已知问题，无法绕过）")


def diagnose() -> dict:
    """给界面用的环境诊断结果。"""
    risk, reason = appbound_risk()
    ff = find_firefox_profiles()
    return {
        "installed": installed_browsers(),
        "appbound_risk": risk,
        "appbound_reason": reason,
        "firefox_profiles": ff,
        "firefox_ok": any(p["exists"] for p in ff),
        "recommendation": ("使用 Firefox 读取，或导出 cookies.txt"
                           if risk else "可直接从浏览器读取 Cookie"),
    }
