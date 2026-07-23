#!/usr/bin/env bash
# Convenience script: start NAT WebUI in background with nohup.
# For foreground / systemd use, see run-prod.sh.
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env.runtime ]; then
  echo "Missing .env.runtime. Run ./scripts/install.sh first or create it from README environment variables." >&2
  exit 1
fi

mkdir -p data logs

set -a
. ./.env.runtime
set +a

HOST="${NAT_WEBUI_HOST:-0.0.0.0}"
PORT="${NAT_WEBUI_PORT:-8788}"
nohup .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" > logs/uvicorn.out 2> logs/uvicorn.err &
echo $! > data/uvicorn.pid
echo "NAT WebUI started on $HOST:$PORT (PID $(cat data/uvicorn.pid))"
