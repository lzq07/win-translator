<#
.SYNOPSIS
    在桌面创建本工具的快捷方式（使用 pythonw.exe，不弹控制台窗口）。

.USAGE
    powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1
    powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1 -Name "翻译工具"
#>
param(
    [string]$Name = "划词翻译"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$entry = Join-Path $projectRoot "main.py"
$icon = Join-Path $projectRoot "assets\icon.ico"

if (-not (Test-Path $entry)) {
    throw "找不到入口文件：$entry"
}

# 优先用 pythonw.exe，避免启动时闪出黑色控制台窗口
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw "命令 python 不存在，请先把 Python 加入 PATH。"
}
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Warning "未找到 pythonw.exe，将使用 python.exe（启动时会带控制台窗口）"
    $pythonw = $python
}

$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "$Name.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$entry`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "划词与截图翻译"
if (Test-Path $icon) {
    $shortcut.IconLocation = "$icon,0"
}
else {
    Write-Warning "未找到图标 $icon，请先运行：python tools\make_icon.py"
}
$shortcut.Save()

Write-Host "已创建快捷方式：$link"
Write-Host "  目标：$pythonw `"$entry`""
Write-Host "  图标：$icon"
