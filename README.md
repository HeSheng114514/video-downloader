# 🎬 视频下载器 (Video Downloader)

一款 **Windows 桌面视频下载工具**，支持 **哔哩哔哩、抖音、快手、TikTok、YouTube、小红书、微博、西瓜视频** 等 1000+ 站点的视频下载。

* 🖥 **图形界面**：Python 内置 tkinter，零第三方 GUI 依赖，开箱即用
* 🚀 **依赖自举**：首次运行自动下载 yt-dlp 与 ffmpeg（多镜像容错 + 断点续传）
* 📋 **批量下载**：一次粘贴多条链接 / 整段分享文案，自动识别平台
* 🎚 **画质可选**：最佳画质 / 4K / 2K / 1080P / 720P / 480P / 仅音频(MP3)
* 🔀 **并发队列**：多任务并发 + 单任务分片并发，支持暂停 / 取消 / 重试
* 🍪 **登录态支持**：可从 Chrome / Edge / Firefox 读取 Cookie，或使用 cookies.txt
* 🌐 **代理支持**：http / https / socks5，YouTube、TikTok 必备

---

## 一、支持平台

| 平台 | 支持情况 | 引擎 | 备注 |
|------|---------|------|------|
| 哔哩哔哩 | ✅ 完整支持 | yt-dlp | 1080P+ 需登录 Cookie |
| YouTube | ✅ 完整支持 | yt-dlp | 国内需配置代理 |
| TikTok | ✅ 完整支持 | yt-dlp | 国内需配置代理 |
| 抖音 | ✅ 支持 | 抖音解析 + yt-dlp | **需登录 Cookie**（见下节） |
| 快手 | ✅ 支持 | 快手解析（自研） | 建议配置 Cookie 以通过验证码 |
| 小红书 / 微博 / 西瓜视频 | ✅ 支持 | yt-dlp | — |
| X(Twitter) / Instagram / Facebook / Twitch / Vimeo | ✅ 支持 | yt-dlp | 国内需代理 |
| 其他 yt-dlp 站点 | ✅ 1000+ | yt-dlp | — |

> **关于抖音**：抖音 Web 接口由 Argus 风控保护，匿名请求会返回
> `403 Blocked by ArgusSecurityPlugin`。程序内置了三种免登录解析尝试，
> 但稳定方案是提供登录 Cookie（浏览器登录抖音后即可一键读取）。
>
> **关于快手**：快手 Web GraphQL 在部分网络/机房 IP 下会要求验证码。
> 程序会依次尝试「移动分享页 → GraphQL → 网页元信息」三条路径，
> 若全部失败会明确提示配置 Cookie。

### 实测验证情况

| 项目 | 状态 |
|------|------|
| 环境自检（`诊断.bat`） | ✅ 21 个模块全部导入通过 |
| 依赖自举（yt-dlp + ffmpeg 6.1.1） | ✅ 自动安装成功（ffmpeg 28 秒装完） |
| 哔哩哔哩 解析 → 下载 → 合并（源码方式） | ✅ 完整跑通：AV1+AAC 双流合并为单个 MP4，中文标题文件名正常 |
| 打包 EXE（PyInstaller 6.22.3） | ✅ 单文件版 21MB / 便携版 10MB+28MB 均构建成功 |
| 打包产物自检 | ✅ `全部通过`，正确识别自带 bin 与内置模块后端 |
| 打包产物真实下载 | ✅ 便携版 EXE 完成「解析 → 下载 → ffmpeg 合并」全流程，输出 20.5MB MP4 |
| 打包产物 GUI 启动 | ✅ 窗口正常弹出，标题「视频下载器 v1.0.0」 |
| 短链归一化（`v.douyin.com` → `douyin.com/video/{id}`） | ✅ 正确跳转识别 |
| 抖音 / 快手 无 Cookie 解析 | ⚠️ 被平台风控拦截，程序给出明确 Cookie 指引（属预期行为） |
| 抖音 / 快手 带 Cookie 解析 | 需在已登录浏览器环境下由用户实测（接口与浏览器同源） |
| GUI 界面构建 / 主题切换 / 进度渲染 | ✅ 冒烟测试通过 |

---

## 二、快速开始

### 方式 1：一键启动（推荐）

双击 **`启动.bat`**。首次运行会自动下载 yt-dlp 与 ffmpeg（约 20~110 MB），
请耐心等待状态栏显示「运行环境就绪」。

### 方式 2：命令行

```bat
python run.py                                   :: 启动图形界面
python run.py --selftest                        :: 环境自检
python run.py --url "视频链接" --out "D:\下载"    :: 无界面下载
python run.py --url "链接" --quality 1080 --cookies-from-browser chrome
```

也可以双击 **`诊断.bat`** 查看环境自检报告。

### 方式 3：打包成独立 EXE（已内置打包脚本）

```powershell
powershell -ExecutionPolicy Bypass -File 构建EXE.ps1
```

脚本会一次性产出两个版本，可直接分发给没装 Python 的电脑：

```
dist\
├── 使用说明.txt
├── 单文件版\              只有一个 exe，方便拷贝传播
│   ├── VideoDownloader.exe        约 21 MB
│   ├── bin\                       yt-dlp.exe / ffmpeg.exe / ffprobe.exe
│   └── vendor\                    内置 yt-dlp 模块（备用通道）
└── 便携版\                目录版，启动更快、更不易被杀软误报
    ├── VideoDownloader.exe        约 10 MB
    ├── _internal\                 运行时依赖
    ├── bin\
    └── vendor\
```

**双后端容错设计**：yt-dlp 被完整打进 exe（`--collect-submodules yt_dlp`），
同时随包附带 `bin\yt-dlp.exe`。程序优先使用 exe（可在线自我更新），
一旦 exe 被杀软拦截或无法运行，会自动通过 `VideoDownloader.exe --ytdlp <参数>`
这条内置通道继续工作，用户无感知。

**运行要求**：Windows 10/11 + Python 3.9 及以上（仅源码方式需要；EXE 方式无需 Python）。

---

## 三、使用说明

1. **粘贴链接**：把视频链接或分享文案（如「7.85 复制打开抖音…」）粘贴进输入框，每行一个
2. **解析**：点「🔍 解析」或按 `Ctrl+Enter`，程序自动识别平台并抓取标题
3. **选画质**：右上角选择画质，勾选「仅音频」可只提取 MP3
4. **开始下载**：点「⬇ 开始下载」
5. **管理任务**：表格实时显示进度 / 速度 / 剩余时间；右键可打开文件、重试、取消、复制链接
6. **双击任务行**：下载完成 → 打开视频；失败 → 重试

### 常用设置（🛠 设置）

| 分类 | 说明 |
|------|------|
| 下载 | 保存目录、文件名模板、画质、音频格式、合集范围、嵌入封面/元数据、下载字幕 |
| 网络与登录 | 代理、浏览器 Cookie、cookies.txt、User-Agent |
| 高级 | 并发数、分片并发、重试次数、限速、主题、额外 yt-dlp 参数 |

---

## 四、Cookie 配置（重要）

抖音、B站高清（1080P+）、YouTube 会员内容等需要登录态。程序支持**三种 Cookie 来源**，
任选其一即可（优先级：手动填写 > cookies.txt 文件 > 浏览器读取）。

**方法 A：手动填写 Cookie（最直接，推荐）**

不受 App-Bound 加密影响，也不需要安装任何扩展：

1. 用浏览器登录目标网站（例如 B 站）
2. 按 `F12` → **Network（网络）** → 刷新页面 → 点任意一个请求
3. 在 **Request Headers（请求标头）** 里找到 `Cookie:` 那一行，**整行复制**
4. 程序 → 🛠 设置 → 网络与登录 → **「✍ 手动填写 Cookie」**
5. 粘贴 → 选择站点（会自动识别）→ 点「解析并保存」

> ⚠ 不要用 console 里的 `document.cookie` —— 它取不到 HttpOnly 的关键 Cookie
> （B 站 `SESSDATA`、抖音 `ttwid` 都是 HttpOnly），会导致登录态不生效。
>
> 💡 也支持直接粘贴整段「Copy as cURL」，程序会自动提取其中的 Cookie。
>
> ✅ 保存后会自动**联网校验登录态**（如 B 站会显示「登录有效：你的昵称（UID xxx）」）。
> 过期的 Cookie 会让站点降级响应（B 站只给 480P），比不传还差，因此建议先校验。

**方法 B：读取浏览器 Cookie（推荐 Firefox）**

1. 用 **Firefox** 登录抖音 / B站 / YouTube 等站点
2. 打开程序 → 🛠 设置 → 网络与登录 → 「从浏览器读取 Cookie」选择 `firefox`
3. 保存后重新解析

> Chrome / Edge 在 Windows 上因 App-Bound 加密**无法**被读取（见下节），
> 选择它们时程序会给出警告并自动降级为无 Cookie 模式。

**方法 C：使用 cookies.txt**

1. 浏览器安装扩展 `Get cookies.txt LOCALLY`
2. 在目标网站页面导出 `cookies.txt`（选择「导出全部 Cookie」）
3. 设置 → 网络与登录 → 选择该文件，点「校验当前 Cookie 配置」可确认是否真的包含登录态

### ⚠ Chrome / Edge 用户必读：App-Bound 加密

Windows 上 **Chrome / Edge 自 127 版起启用了 App-Bound 加密**，Cookie 解密密钥由浏览器
进程独占保护，任何外部程序都无法用 DPAPI 解开，yt-dlp 会报：

```
ERROR: Failed to decrypt with DPAPI
```

这是**浏览器侧的安全机制，yt-dlp 官方明确表示无法绕过**
（[yt-dlp#10927](https://github.com/yt-dlp/yt-dlp/issues/10927)，master 分支至今无相关实现），
所以 `--cookies-from-browser chrome/edge` 在 Windows 上不可用。

**本程序的处理方式**：

1. **自动降级**：检测到该错误时自动去掉 Cookie 重新解析/下载，任务不会直接失败
   （公共视频仍可正常下载，画质可能受限），日志中给出明确原因与建议
2. **🍪 Cookie 助手**：设置 → 网络与登录 → 「Cookie 助手」，提供四种方案
   * **手动粘贴 Cookie**（最直接，不用装扩展）
   * 一键切换到 Firefox（其 Cookie 未加密，可直接读取）
   * 选择并**校验** cookies.txt（检查是否真的包含目标站点的关键登录 Cookie）
   * 环境诊断 + 直达扩展安装页与官方说明
3. **✍ 手动填写 Cookie**：独立入口，支持站点头像自动识别、联网校验登录态、多域名管理

**结论**：Windows 上推荐「✍ 手动填写 Cookie」（最简单），或使用 Firefox / cookies.txt。

### 关于画质上限（为什么只有 720P / 960P）

解析时日志会输出该视频的**全部可用画质**，例如：

```
可用画质：1080P / 720P / 480P / 360P（最高 1080P）
ℹ 你选择的画质为 1080P，但此视频最高只有 720P；该视频可能需要登录才能解锁更高画质，可在「设置 → 网络与登录 → Cookie 助手」配置 Cookie 后重试
```

最高画质低于预期通常就是「未登录」导致的（B 站 1080P、抖音高清均需登录态），
配置 Cookie 后重新解析即可。若日志显示的视频最高画质本就是 960P，说明该视频源本身
只有这个清晰度（竖屏短视频常见），与登录无关。

### 更新日志

* **v1.1.0**
  * 新增：**✍ 手动填写 Cookie** —— 直接从 F12 请求头粘贴 Cookie，无需扩展、不受 App-Bound 限制
    * 自动识别所属站点并填充域名（也支持粘贴整段「Copy as cURL」）
    * **联网校验登录态**（B 站显示昵称与 UID，YouTube 检测登录标识），避免用过期的 Cookie 反而降画质
    * 多域名管理：可分别保存/删除 B 站、抖音等各自的 Cookie，实时预览识别到的 Cookie 名单
    * 运行时会自动转成标准 Netscape 格式供 yt-dlp 与自研引擎（抖音/快手）共用
  * 新增：命令行 `--cookie-string "SESSDATA=xxx; bili_jct=yyy"` 与 `--cookie-domain`
  * 调整：Cookie 优先级明确为「手动填写 > cookies.txt > 浏览器读取」，三者互斥避免混淆
* **v1.0.1**
  * 修复：Chrome / Edge Cookie 读取失败（App-Bound 加密）不再导致任务直接失败，自动降级重试
  * 新增：🍪 Cookie 助手（环境诊断 / Firefox 一键切换 / cookies.txt 校验）
  * 新增：解析时显示可用画质列表，并在画质低于所选档位时说明原因
  * 优化：子进程输出编码自适应（UTF-8 / GBK），避免中文标题与路径乱码
* **v1.0.0** 首个开源版本

---

## 五、代理配置

YouTube / TikTok / Instagram 等站点在中国大陆需要代理：

* 设置 → 网络与登录 → 代理服务器，填写如 `http://127.0.0.1:7890`
* 也支持 `socks5://127.0.0.1:1080`

---

## 六、常见问题

| 现象 | 原因与解决 |
|------|-----------|
| 提示「未找到 yt-dlp」 | 打开 ⚙ 运行环境 → 一键安装 / 修复 |
| YouTube 下载很慢或失败 | 配置代理；或在设置中提高「单任务分片并发」 |
| 抖音提示需要 Cookie | 按第四节配置浏览器 Cookie（浏览器须已登录抖音） |
| 只有 720P，没有 1080P | 该站点高清需登录，配置 Cookie 后重新解析 |
| 快手提示验证码 | 配置快手 Cookie；或更换网络后重试 |
| 下载的视频没有声音 / 只有画面 | 缺少 ffmpeg，打开 ⚙ 运行环境一键安装 |
| 杀毒软件报毒 | PyInstaller 打包程序的常见误报，添加信任即可 |
| 下载中断 | 程序支持断点续传，右键任务「重新下载」即可续传 |

---

## 七、目录结构

```
D-视频下载/
├── 启动.bat               一键启动（图形界面）
├── 诊断.bat               环境自检
├── 构建EXE.ps1            打包成独立 EXE
├── run.py                 入口
├── config.json            配置（首次运行生成）
├── bin/                   yt-dlp.exe / ffmpeg.exe（自动下载）
├── vendor/                yt-dlp Python 模块（pip 方式安装时使用）
├── .cache/                临时文件（解析/下载中间产物）
├── logs/                  日志
└── app/
    ├── main.py            程序入口（GUI / CLI 分发）
    ├── cli.py             命令行模式与自检
    ├── paths.py           路径与运行环境解析
    ├── config.py          配置读写
    ├── models.py          任务与媒体数据模型
    ├── manager.py         任务调度（并发 / 暂停 / 重试 / 引擎兜底）
    ├── bootstrap.py       yt-dlp / ffmpeg 自动安装（多镜像）
    ├── net.py             HTTP 客户端（断点续传 / 代理 / SSL）
    ├── platforms.py       平台识别与链接归一化
    ├── utils.py           通用工具
    ├── engines/
    │   ├── ytdlp.py       yt-dlp 引擎（主力，1000+ 站点）
    │   ├── douyin.py      抖音解析引擎（多策略）
    │   ├── kuaishou.py    快手解析引擎（多策略）
    │   └── direct.py      直链下载与落盘
    └── ui/
        ├── main_window.py 主窗口
        ├── settings.py    设置对话框
        ├── env_dialog.py  运行环境管理
        └── theme.py       浅色 / 深色主题
```

---

## 八、技术说明

* **引擎链式兜底**：每个链接按平台生成引擎优先级列表，主力引擎失败自动切换备用引擎，
  并把失败原因汇总提示。抖音在配置 Cookie 时优先 yt-dlp，否则优先自研解析。
* **链接归一化**：`v.douyin.com/xxx` → `douyin.com/video/{id}`，
  `v.kuaishou.com/xxx` → `kuaishou.com/short-video/{id}`，让 yt-dlp 能够接手短链。
* **零依赖**：核心仅使用 Python 标准库（tkinter / urllib / subprocess / zipfile），
  不依赖 requests、Pillow、PySide 等第三方包，打包与分发更省心。
* **依赖自举**：
  * yt-dlp：GitHub 直链 → gh-proxy / ghfast / ghproxy.net 等加速代理；
    若直链源都不可用，则从 **PyPI 国内镜像**（阿里云 / 腾讯云 / 中科大）安装 yt-dlp
    **Python 模块**。程序支持三种后端（`bin\yt-dlp.exe` / PATH / Python 模块）并自动择优。
  * ffmpeg：优先 **npmmirror 的 ffmpeg-static b6.1.1 裸二进制**（28MB，国内实测可达 10MB/s，
    含 ffmpeg + ffprobe，支持 AV1/H.265），其次 gyan.dev / BtbN 官方完整构建，
    最后 npm 精简版兜底。
* **分块下载**：依赖与直链媒体均采用「固定大小 Range 请求 + 逐块写入」，
  在被代理掐断长连接的网络下依然能完整下载，并支持断点续传。
* **慢源守护**：某镜像 45 秒内下载不足 1.5MB 会被判定不可用并自动切换下一个源，
  避免卡在慢速源上（实测国内访问 GitHub 直链可能只有几十 KB/s）。
* **进度解析**：通过 `--progress-template` 的 JSON 模板获取精确进度/速度/ETA，
  并通过 `--print-to-file after_move:%(filepath)s` 以 UTF-8 回传最终文件路径，
  规避 Windows 控制台编码问题。
* **平台专用解析**：抖音与快手接口变动频繁，程序为二者分别实现多策略解析
  （抖音：IES 移动接口 / Web 详情接口 / 分享页 HTML；快手：移动分享页 / GraphQL / 网页元信息），
  任一策略成功即返回；全部失败时给出针对该平台的明确处理建议。
* **假成功防护**：yt-dlp 的通用解析器有时会把普通网页误判为视频，
  程序会校验 extractor 类型与标题有效性，避免出现「标题就是链接」的假成功。
* **无 ffmpeg 降级**：未安装 ffmpeg 时自动改用单文件（渐进式）格式，避免下载出
  分离的音视频文件；「仅音频」模式则会明确提示需要 ffmpeg。

---

## 九、开源许可

本项目采用 **GNU General Public License v3.0（GPL-3.0）** 开源，全文见 [LICENSE](LICENSE)。

```
Copyright (C) 2026 视频下载器 contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
```

这意味着你可以自由使用、修改、再分发本项目，但**衍生作品必须同样以 GPL-3.0 开源**。

### 从源码运行

```bash
git clone https://github.com/HeSheng114514/video-downloader.git
cd video-downloader
python run.py            # 首次运行会自动下载 yt-dlp 与 ffmpeg
```

> 仓库中不包含 `bin/`（yt-dlp / ffmpeg 二进制）与 `dist/`（打包产物），
> 它们体积较大且可自动获取，因此通过 `.gitignore` 排除。
> 打包好的可执行文件请到 **Releases** 页面下载。

### 第三方组件

| 组件 | 许可 | 用途 |
|------|------|------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | 视频解析与下载引擎 |
| [FFmpeg](https://ffmpeg.org/) | LGPL / GPL | 音视频合并与音频提取 |

两者均以独立可执行文件形式在运行时按需下载，不包含在本仓库源码中。

---

## 十、免责声明

本工具仅供个人学习、研究与备份个人合法获取的内容使用。
请遵守各平台的服务条款与著作权法律法规，不要用于商业用途或传播侵权内容。
