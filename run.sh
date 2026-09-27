#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Alejandro Criado-Perez <alejandro@criadoperez.com>
# One-command launcher: loads .env, ensures deps, starts the bridge.
# Usage: ./run.sh   (reads backends.yaml via LHB_BACKENDS in .env)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Missing .env (copy from .env.example and fill the keys)." >&2
  exit 1
fi
if [ ! -f backends.yaml ]; then
  echo "Missing backends.yaml (copy from backends.yaml.example)." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  PY=python3
fi

if ! "$PY" -c "import fastapi, httpx, yaml, websockets" 2>/dev/null; then
  echo "Installing dependencies into .venv..." >&2
  "$(command -v python3)" -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  PY=.venv/bin/python
fi

# The code lives in src/ layout: ensure it is importable, either via an
# editable install or via PYTHONPATH fallback (fresh clones).
if ! "$PY" -c "import live_hermes_bridge.server" 2>/dev/null; then
  if "$PY" -m pip install -q -e . 2>/dev/null; then
    : # editable install worked; `live-hermes-bridge` command is now available too
  else
    export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"
  fi
fi

exec "$PY" -m live_hermes_bridge.server
