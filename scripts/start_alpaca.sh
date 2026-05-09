#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a
source env/alpaca.env
set +a
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
