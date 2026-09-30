# Установка yt-studio для Claude Code на Windows (PowerShell).
# Запуск из папки скилла:  powershell -ExecutionPolicy Bypass -File install.ps1
# Удаление:                powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
# Личные данные (voice.md, журнал) лежат в ~\.claude\yt-studio и при обновлении и удалении не трогаются.
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
$dest = Join-Path $base "skills\yt-studio"

if ($Uninstall) {
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Write-Host "yt-studio удалён. voice.md и журнал остались в ~\.claude\yt-studio"
  exit 0
}

$py = $null
foreach ($c in @("python3", "python", "py")) {
  if (Get-Command $c -ErrorAction SilentlyContinue) {
    try {
      & $c -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
      if ($LASTEXITCODE -eq 0) { $py = $c; break }
    } catch { }
  }
}
if (-not $py) { Write-Error "Нужен Python 3.8 или новее: winget install Python.Python.3.12"; exit 1 }
if (-not (Test-Path (Join-Path $src "SKILL.md"))) { Write-Error "Рядом с install.ps1 нет SKILL.md - запускай скрипт из папки скилла."; exit 1 }

if ($src -ne $dest) {
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  foreach ($item in @("SKILL.md", "README.md", "LICENSE", "scripts", "references", "data", "templates")) {
    Copy-Item -Recurse -Force (Join-Path $src $item) $dest
  }
  Get-ChildItem -Path $dest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
}

& $py (Join-Path $dest "scripts\doctor.py") --init
Write-Host "Установлено в $dest"
Write-Host "Перезапусти Claude Code и напиши: 'что умеет yt-studio?' или сразу 'придумай хук для видео про ...'"
