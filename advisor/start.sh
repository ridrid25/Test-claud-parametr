#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export COMMERCE_AGENTS_DIR="${COMMERCE_AGENTS_DIR:-$ROOT/../commerce-agents}"
cd "$ROOT"
exec "$COMMERCE_AGENTS_DIR/.venv/bin/python" -m advisor.server
