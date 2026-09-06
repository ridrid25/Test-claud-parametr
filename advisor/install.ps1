# Установка сервера-советника (Windows PowerShell).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$CA = if ($env:COMMERCE_AGENTS_DIR) { $env:COMMERCE_AGENTS_DIR } else { Join-Path (Split-Path -Parent $Root) "commerce-agents" }
if (-not (Test-Path $CA)) { git clone --depth 1 https://github.com/anthropics/commerce-agents $CA }
$Py = Join-Path $CA ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { python -m venv (Join-Path $CA ".venv") }
& $Py -m pip install -q -r (Join-Path $CA "requirements.txt")
Write-Host "Готово. Запуск: `$env:PILOT_ANTHROPIC_KEY = 'sk-ant-...'; .\advisor\start.ps1"
