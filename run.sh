#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
if [ ! -d .venv ]; then
  echo 'Chưa có .venv. Cài theo README.md: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt'
  exit 1
fi
exec .venv/bin/python ig_following.py
