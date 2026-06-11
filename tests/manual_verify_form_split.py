import os
import sys
import tempfile
import types
from pathlib import Path

os.environ.setdefault("NAT_WEBUI_DB_PATH", tempfile.mktemp(prefix="nat_webui_verify_", suffix=".db"))
sys.path.insert(0, str(Path.cwd()))

try:
    from fastapi.testclient import TestClient
    from app.main import app
except ModuleNotFoundError as exc:
    print(f"SKIP missing dependency: {exc}")
    raise SystemExit(0)

client = TestClient(app)
client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)

single = client.get("/nodes/new")
chain = client.get("/nodes/new-chain")
listing = client.get("/nodes")

assert single.status_code == 200
assert "NAT IP" in single.text
assert "SSH 端口" in single.text
assert "前置节点" not in single.text
assert "新建链式节点" in single.text

assert chain.status_code == 200
assert "前置节点" in chain.text
assert "后端节点" in chain.text
assert "NAT IP" not in chain.text
assert "切到单节点" in chain.text

assert listing.status_code == 200
assert "/nodes/new-chain" in listing.text
assert "/nodes/new" in listing.text
print("form split ok")
