#!/usr/bin/env sh
set -eu
cd "${NAT_WEBUI_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
set -a
. ./.env.runtime
set +a
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${NAT_WEBUI_PORT:-8788}"
