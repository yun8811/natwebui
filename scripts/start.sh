#!/usr/bin/env bash
# Convenience script: start NAT WebUI in background with nohup.
# For foreground / systemd use, see run-prod.sh.
set -eu
cd "$(dirname "$0")/.."
set -a
. ./.env.runtime
set +a

PORT="${NAT_WEBUI_PORT:-8788}"
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" > logs/uvicorn.out 2> logs/uvicorn.err &
echo $! > data/uvicorn.pid
echo "NAT WebUI started on port $PORT (PID $(cat data/uvicorn.pid))"
