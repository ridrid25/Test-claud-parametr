#!/usr/bin/env bash
# Установка сервера-советника: клон commerce-agents рядом с проектом + venv + зависимости.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CA="${COMMERCE_AGENTS_DIR:-$ROOT/../commerce-agents}"
if [ ! -d "$CA" ]; then git clone --depth 1 https://github.com/anthropics/commerce-agents "$CA"; fi
if [ ! -x "$CA/.venv/bin/python" ]; then python3 -m venv "$CA/.venv"; fi
"$CA/.venv/bin/pip" install -q -r "$CA/requirements.txt"
echo "Готово. Запуск: export PILOT_ANTHROPIC_KEY=... && bash advisor/start.sh"
