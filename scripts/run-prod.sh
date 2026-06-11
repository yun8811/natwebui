#!/usr/bin/env sh
set -eu
cd /root/.nanobot/workspace/nat-webui-project
set -a
. ./.env.runtime
set +a
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8788
