#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_DIR"
python3 -m venv .venv
. ./.venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data logs
if [ ! -f .env.runtime ]; then
  SECRET=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)
  PASSWORD=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)
  cat > .env.runtime <<EOF
NAT_WEBUI_SESSION_SECRET='$SECRET'
NAT_WEBUI_ADMIN_USERNAME='admin'
NAT_WEBUI_ADMIN_PASSWORD='$PASSWORD'
NAT_WEBUI_HOST='0.0.0.0'
NAT_WEBUI_PORT='8788'
EOF
  echo "Created .env.runtime"
  echo "Default login: admin / $PASSWORD"
else
  echo ".env.runtime already exists; keep existing config"
fi
echo "Install complete. Start with: ./scripts/run-prod.sh"
