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

# 手动 Cookie 的默认写入域名（带前导点以匹配子域）
PLATFORM_DOMAINS: dict[str, str] = {
    "bilibili": ".bilibili.com",
    "douyin": ".douyin.com",
    "kuaishou": ".kuaishou.com",
    "youtube": ".youtube.com",
    "tiktok": ".tiktok.com",
    "xiaohongshu": ".xiaohongshu.com",
    "weibo": ".weibo.com",
    "twitter": ".x.com",
}

MANUAL_COOKIE_FILE = "manual_cookies.txt"


# ------------------------------------------------------------------ 手动 Cookie

def parse_cookie_string(text: str) -> dict[str, str]:
    """把用户粘贴的内容解析成 {name: value}。

    支持多种来源格式：

    * DevTools → Network → 请求头里的 ``Cookie: a=b; c=d``
    * ``document.cookie`` 形式的 ``a=b; c=d``
    * 每行一个 ``name=value``
    * 整段「Copy as cURL」，会自动提取其中的 Cookie 部分
    """
    if not text:
        return {}
    raw = text.strip()

    # 从 cURL / 请求头中提取 Cookie 段
    m = re.search(r"(?im)^\s*(?:-H\s+)?['\"]?cookie\s*:\s*(.+?)(?:['\"]?\s*\\?\s*$)", raw, re.M)
    if m:
        raw = m.group(1)
    else:
        m2 = re.search(r"(?is)\bcookie\s*:\s*(.+)", raw)
        if m2 and "\n" not in m2.group(1).strip():
            raw = m2.group(1)

    raw = raw.replace("\\\n", " ").replace("\\r", " ").replace("\\n", " ")
    pairs: dict[str, str] = {}
    for chunk in re.split(r"[;\n\r]+", raw):
        item = chunk.strip().strip("'\"")
        if not item or "=" not in item:
            continue
        name, _, value = item.partition("=")
        name = name.strip().strip("'\"")
        value = value.strip().strip("'\"")
        if not name or name.lower() in ("cookie", "path", "domain", "expires", "max-age",
                                        "secure", "httponly", "samesite"):
            continue
        pairs[name] = value
    return pairs


def guess_platform(cookie_names) -> str | None:
    """根据 Cookie 名称猜测所属站点。"""
    names = set(cookie_names)
    best: tuple[int, str] | None = None
    for platform, (_domains, keys) in EXPECTED_COOKIES.items():
        hit = len(names & set(keys))
        if hit and (best is None or hit > best[0]):
            best = (hit, platform)
    return best[1] if best else None


def format_cookie_string(pairs: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in pairs.items())


def write_netscape(path: str | Path, entries: dict[str, str]) -> int:
    """把 {域名: "a=b; c=d"} 写成 Netscape 格式 cookies.txt，返回写入条数。

    选用该格式是因为 yt-dlp 与程序内自研引擎（抖音/快手）都直接支持，
    等价于用户手工导出的 cookies.txt，兼容性最好。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File",
             "# 由视频下载器根据「手动填写 Cookie」自动生成，请勿手工编辑",
             ""]
    count = 0
    expiry = 4102444800  # 2100-01-01
    for domain, cookie_str in (entries or {}).items():
        dom = (domain or "").strip()
        if not dom:
            continue
        if not dom.startswith("."):
            dom = "." + dom
        pairs = parse_cookie_string(cookie_str)
        for name, value in pairs.items():
            if not name:
                continue
            lines.append("\t".join([dom, "TRUE", "/", "TRUE", str(expiry), name, value]))
            count += 1
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def manual_cookie_file_path(tmp_dir: str | Path) -> Path:
    return Path(tmp_dir) / MANUAL_COOKIE_FILE


def effective_cookie_header(cfg, domain_hint: str = "") -> str:
    """取得用于自研引擎（抖音/快手）请求的 Cookie 头。

    优先级：手动填写的 Cookie > cookies.txt 文件
    """
    manual = getattr(cfg, "manual_cookies", None) or {}
    if isinstance(manual, dict):
        merged: dict[str, str] = {}
        for domain, cookie_str in manual.items():
            if domain_hint and domain_hint not in domain:
                continue
            merged.update(parse_cookie_string(cookie_str))
        if merged:
            return format_cookie_string(merged)
    return read_cookie_header(getattr(cfg, "cookies_file", ""), domain_hint)


def manual_cookie_summary(manual: dict) -> str:
    """给界面用的一句话摘要。"""
    if not manual:
        return "未填写"
    total = sum(len(parse_cookie_string(v)) for v in manual.values())
    return f"{len(manual)} 个域名 / 共 {total} 条 Cookie"


# ------------------------------------------------------------------ 有效性校验

def platform_from_domain(domain: str) -> str | None:
    """根据域名反查站点标识。"""
    dom = (domain or "").lstrip(".").lower()
    if not dom:
        return None
    for platform, (domains, _keys) in EXPECTED_COOKIES.items():
        for d in domains:
            if dom == d or dom.endswith("." + d) or d.endswith("." + dom):
                return platform
    return None


def check_cookie_validity(platform: str, cookie_str: str, client) -> tuple[bool | None, str]:
    """联网校验 Cookie 是否仍然有效（登录态）。

    过期或错误的 Cookie 会导致站点降级响应（例如 B 站只给 480P），
    比不传 Cookie 还差，因此保存前校验很有必要。

    返回 (是否有效 | None 表示无法判断, 说明文字)
    """
    pairs = parse_cookie_string(cookie_str)
    if not pairs:
        return False, "没有可用的 Cookie"

    if platform == "bilibili" or "SESSDATA" in pairs:
        try:
            resp = client.get("https://api.bilibili.com/x/web-interface/nav",
                              headers={"Cookie": format_cookie_string(pairs),
                                       "Referer": "https://www.bilibili.com/"},
                              timeout=15)
            data = resp.json()
            d = data.get("data") or {}
            if data.get("code") == 0 and d.get("isLogin"):
                return True, f"登录有效：{d.get('uname') or '已登录'}（UID {d.get('mid')}）"
            return False, "Cookie 无效或已过期（B 站返回未登录），请重新登录后复制"
        except Exception as e:
            return None, f"无法校验（{type(e).__name__}）"

    if platform == "youtube" or any(k in pairs for k in ("SAPISID", "__Secure-1PSID", "SID")):
        try:
            resp = client.get("https://www.youtube.com/",
                              headers={"Cookie": format_cookie_string(pairs)},
                              timeout=20)
            text = resp.text
            if '"LOGGED_IN":true' in text or "LOGGED_IN: true" in text:
                return True, "登录有效（YouTube 已识别登录态）"
            if '"LOGGED_IN":false' in text or "LOGGED_IN: false" in text:
                return False, "Cookie 无效或已过期（YouTube 显示未登录）"
            return None, "无法判断（页面未包含登录标识）"
        except Exception as e:
            return None, f"无法校验（{type(e).__name__}）"

    return None, "该站点暂不支持自动校验，若下载异常请重新登录后复制 Cookie"


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
