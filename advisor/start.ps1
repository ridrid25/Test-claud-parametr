# Запуск сервера-советника (Windows PowerShell). Ключ: $env:PILOT_ANTHROPIC_KEY.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $env:COMMERCE_AGENTS_DIR) { $env:COMMERCE_AGENTS_DIR = Join-Path (Split-Path -Parent $Root) "commerce-agents" }
$env:PYTHONUTF8 = "1"
Set-Location $Root
& (Join-Path $env:COMMERCE_AGENTS_DIR ".venv\Scripts\python.exe") -m advisor.server
