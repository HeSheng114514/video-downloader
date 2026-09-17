<#
    视频下载器 —— 一键打包脚本（单文件版 + 便携版）
    用法：  powershell -ExecutionPolicy Bypass -File 构建EXE.ps1

    产物：
      dist\单文件版\VideoDownloader.exe          单文件，方便拷贝
      dist\单文件版\bin\                         运行环境（yt-dlp / ffmpeg / ffprobe）
      dist\单文件版\vendor\                      内置 yt-dlp 模块（exe 被杀软拦截时的后备通道）
      dist\便携版\                               目录版，启动更快、更不易被杀软误报
      dist\使用说明.txt

    设计要点：
      · yt-dlp 完整模块通过 --collect-submodules 打进 exe，
        因此即使 bin\yt-dlp.exe 无法运行（杀软拦截、临时目录受限），
        程序仍可用 `VideoDownloader.exe --ytdlp <参数>` 这条内置通道工作。
      · 运行环境（bin）不打包进 exe，以目录形式随包发布，便于单独更新 yt-dlp。
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Err($msg)  { Write-Host "    $msg" -ForegroundColor Red }

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  视频下载器 —— EXE 打包" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. Python
Write-Step "1/6 检查 Python"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { Write-Err "未找到 Python，请先安装 Python 3.9+"; exit 1 }
Write-Ok $python

# ---------------------------------------------------------------- 2. PyInstaller
Write-Step "2/6 准备 PyInstaller"
$mirrors = @(
    "https://mirrors.aliyun.com/pypi/simple/",
    "https://mirrors.cloud.tencent.com/pypi/simple/",
    "https://pypi.org/simple/"
)
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "已安装，跳过"
} else {
    $ok = $false
    foreach ($m in $mirrors) {
        Write-Host "    尝试镜像：$m"
        $h = ($m -split "//")[1].Split("/")[0]
        python -m pip install pyinstaller -i $m --trusted-host $h --disable-pip-version-check
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    }
    if (-not $ok) { Write-Err "PyInstaller 安装失败，请检查网络"; exit 1 }
    Write-Ok "安装完成"
}

# ---------------------------------------------------------------- 3. yt-dlp 模块
Write-Step "3/6 准备内置 yt-dlp 模块（vendor）"
$vendor = Join-Path $Root "vendor"
if (-not (Test-Path (Join-Path $vendor "yt_dlp\__init__.py"))) {
    Write-Host "    vendor 中缺少 yt_dlp，尝试通过镜像安装…"
    New-Item -ItemType Directory -Force -Path $vendor | Out-Null
    $ok = $false
    foreach ($m in $mirrors) {
        $h = ($m -split "//")[1].Split("/")[0]
        python -m pip install --target $vendor --upgrade --no-cache-dir --disable-pip-version-check `
            -i $m --trusted-host $h yt-dlp
        if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    }
    if (-not $ok) { Write-Host "    [警告] yt-dlp 模块安装失败，将不包含内置后备通道（程序仍会联网下载 yt-dlp.exe）" -ForegroundColor Yellow }
} else {
    Write-Ok "已就绪"
}

# ---------------------------------------------------------------- 4. 清理
Write-Step "4/6 清理旧产物"
foreach ($d in @("build", "dist", "__pycache__")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
}
Get-ChildItem -Path $Root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "dist\单文件版", "dist\便携版" | Out-Null
Write-Ok "完成"

# ---------------------------------------------------------------- 5. 打包
$common = @(
    "--noconfirm", "--clean", "--noconsole", "--name", "VideoDownloader",
    "--paths", $vendor,
    "--collect-submodules", "yt_dlp",
    "--hidden-import", "optparse",
    "--hidden-import", "app.main",
    "--hidden-import", "app.cli",
    "--hidden-import", "app.ui.main_window",
    "--hidden-import", "app.ui.settings",
    "--hidden-import", "app.ui.env_dialog",
    "--hidden-import", "app.engines.ytdlp",
    "--hidden-import", "app.engines.douyin",
    "--hidden-import", "app.engines.kuaishou",
    "--exclude-module", "numpy",
    "--exclude-module", "PIL",
    "--exclude-module", "matplotlib",
    "--exclude-module", "unittest"
)

Write-Step "5/6 打包单文件版"
python -m PyInstaller @common --onefile --distpath "dist\单文件版" --workpath "build\onefile" --specpath build "run.py"
if ($LASTEXITCODE -ne 0) { Write-Err "单文件版打包失败"; exit 1 }
Write-Ok "dist\单文件版\VideoDownloader.exe"

Write-Step "6/6 打包便携版"
python -m PyInstaller @common --onedir --distpath "build\onedir" --workpath "build\onedir-work" --specpath build "run.py"
if ($LASTEXITCODE -ne 0) { Write-Err "便携版打包失败"; exit 1 }
Copy-Item "build\onedir\VideoDownloader\*" "dist\便携版\" -Recurse -Force
Write-Ok "dist\便携版\VideoDownloader.exe"

# ---------------------------------------------------------------- 运行环境
Write-Host "`n==> 附带运行环境"
foreach ($v in @("单文件版", "便携版")) {
    if (Test-Path "bin") {
        Copy-Item "bin" "dist\$v\bin" -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok "dist\$v\bin"
    } else {
        Write-Host "    [提示] 未找到 bin 目录，程序将在首次运行时自动下载 yt-dlp / ffmpeg" -ForegroundColor Yellow
    }
    if (Test-Path (Join-Path $vendor "yt_dlp")) {
        Copy-Item $vendor "dist\$v\vendor" -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok "dist\$v\vendor"
    }
}
if (Test-Path "使用说明.txt") {
    Copy-Item "使用说明.txt" "dist\使用说明.txt" -Force
    Write-Ok "dist\使用说明.txt"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  打包完成 ✔" -ForegroundColor Green
Write-Host "    dist\单文件版\   单文件，方便分发" -ForegroundColor Green
Write-Host "    dist\便携版\     目录版，启动更快、更不易被杀软误报" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
