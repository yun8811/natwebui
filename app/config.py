from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = Path(os.getenv("NAT_WEBUI_DB_PATH", str(DATA_DIR / "nat-webui.db")))

APP_NAME = os.getenv("NAT_WEBUI_APP_NAME", "NAT WebUI")
SESSION_COOKIE = os.getenv("NAT_WEBUI_SESSION_COOKIE", "nat_webui_session")
SESSION_SECRET = os.getenv("NAT_WEBUI_SESSION_SECRET", "change-me-before-production")
ADMIN_USERNAME = os.getenv("NAT_WEBUI_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("NAT_WEBUI_ADMIN_PASSWORD", "change-me-before-production")
STATUS_STALE_MINUTES = int(os.getenv("NAT_WEBUI_STATUS_STALE_MINUTES", "15"))
AGENT_REPORT_PATH = os.getenv("NAT_WEBUI_AGENT_REPORT_PATH", "/agent/report")
PUBLIC_BASE_URL = os.getenv("NAT_WEBUI_PUBLIC_BASE_URL", "").rstrip("/")
