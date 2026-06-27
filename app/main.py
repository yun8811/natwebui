from __future__ import annotations

import base64
import ipaddress
import json
import re
import sqlite3
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import yaml
from fastapi import FastAPI, Form, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import login_required, verify_login
from .chain_deployer import apply_front_chain_config
from .config import AGENT_REPORT_PATH, APP_DIR, APP_NAME, SESSION_COOKIE, SESSION_SECRET, STATUS_STALE_MINUTES
from .db import (
    DB_PATH,
    create_demo_node,
    create_deployment_record,
    create_node_record,
    delete_node_record,
    delete_tag,
    find_direct_vless_port_conflict,
    find_node_by_endpoint,
    get_deployment,
    get_node,
    get_or_create_subscription_token,
    get_subscription_token_state,
    redact_sensitive_text,
    rotate_subscription_token,
    ingest_agent_report,
    init_db,
    list_chain_backend_nodes,
    list_deployments_for_node,
    list_direct_vless_nodes,
    list_node_tag_ids,
    list_node_tags_map,
    list_nodes,
    list_subscribable_nodes,
    list_tags,
    mark_node_deployed_from_report,
    rename_node_record,
    set_node_tags,
    create_tag,
    update_node_record,
    validate_subscription_token,
)
from .jobs import is_deploy_running, submit_reinstall_job
from .regions import country_code_to_badge, country_code_to_flag, lookup_region_by_host, region_from_node, replace_vless_fragment, vless_remark_for_node

app = FastAPI(title=APP_NAME)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie=SESSION_COOKIE,
)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    create_demo_node()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get("auth"):
        return RedirectResponse(url="/nodes", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "title": "登录", "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not verify_login(username, password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "title": "登录", "error": "用户名或密码错误"},
            status_code=401,
        )
    request.session["auth"] = True
    return RedirectResponse(url="/nodes", status_code=303)


@app.post(AGENT_REPORT_PATH)
async def agent_report_ingest(request: Request):
    payload = await request.json()
    node_id = str(payload.get("node_id", "")).strip()
    agent_token = str(payload.get("agent_token", "")).strip()
    if not node_id or not agent_token:
        return JSONResponse({"ok": False, "error": "missing_node_id_or_token"}, status_code=400)

    node = get_node(node_id)
    if not node:
        return JSONResponse({"ok": False, "error": "node_not_found"}, status_code=404)
    if agent_token != (node["agent_token"] or ""):
        return JSONResponse({"ok": False, "error": "invalid_agent_token"}, status_code=403)

    overall_status = str(payload.get("overall_status", "online")).strip() or "online"
    report_time = str(payload.get("report_time", "")).strip() or datetime.now(timezone.utc).isoformat()
    ingest_agent_report(node_id, overall_status, json.dumps(payload, ensure_ascii=False), report_time=report_time)
    mark_node_deployed_from_report(node_id, payload)
    return JSONResponse({"ok": True})


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


REQUIRED_FIELDS = [
    "name",
    "ip",
    "ssh_port",
    "ssh_user",
    "ssh_password",
    "public_port",
    "listen_port",
]
TAG_COLORS = ["#4c8dff", "#2ccf8f", "#f0b84b", "#ff6b7a", "#a78bfa", "#22d3ee", "#fb7185", "#94a3b8"]
CHAIN_MODE = "vless_reality_to_vless_reality"
PROTOCOL_DIRECT = "vless_reality_singbox"
PROTOCOL_CHAIN = "vless_chain"
PROTOCOL_TUNNEL = "cf_vless_ws"
PROTOCOL_IMPORT = "imported_vless"


def is_chain_protocol(protocol_type: object) -> bool:
    return str(protocol_type or "") == PROTOCOL_CHAIN


def is_tunnel_protocol(protocol_type: object) -> bool:
    return str(protocol_type or "") == PROTOCOL_TUNNEL


def is_import_protocol(protocol_type: object) -> bool:
    return str(protocol_type or "") == PROTOCOL_IMPORT



def is_direct_vless_protocol(protocol_type: object) -> bool:
    return str(protocol_type or "") in {"", PROTOCOL_DIRECT}


def is_chain_backend_protocol(protocol_type: object) -> bool:
    return str(protocol_type or "") in {PROTOCOL_DIRECT, PROTOCOL_IMPORT}



def node_to_form_values(node) -> dict[str, object]:
    return {
        "name": node["name"],
        "ip": node["ip"],
        "ssh_port": node["ssh_port"],
        "ssh_user": node["ssh_user"],
        "ssh_password": node["ssh_password"],
        "public_port": node["public_port"],
        "listen_port": node["listen_port"],
        "protocol_type": node["protocol_type"],
        "front_node_id": node["front_node_id"],
        "backend_node_id": node["backend_node_id"],
        "chain_mode": node["chain_mode"],
        "manual_country_code": node["manual_country_code"] or "",
        "manual_region_label": node["manual_region_label"] or "",
        "selected_reality_target": node["selected_reality_target"] or "www.example.com",
        "cf_host": node["cf_host"] or "",
        "cf_tunnel_token": node["cf_tunnel_token"] or "",
        "ws_port": node["ws_port"] or 8080,
        "ws_path": node["ws_path"] or "/",
        "last_vless_link": node["last_vless_link"] or "",
    }



def default_form_values() -> dict[str, object]:
    return {
        "name": "",
        "ip": "",
        "ssh_port": 22,
        "ssh_user": "root",
        "ssh_password": "",
        "public_port": "",
        "listen_port": "",
        "protocol_type": PROTOCOL_DIRECT,
        "front_node_id": "",
        "backend_node_id": "",
        "chain_mode": CHAIN_MODE,
        "manual_country_code": "",
        "manual_region_label": "",
        "selected_reality_target": "www.example.com",
        "cf_host": "",
        "cf_tunnel_token": "",
        "ws_port": 8080,
        "ws_path": "/",
        "last_vless_link": "",
    }



def normalize_host_value(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("https://", "").replace("http://", "").strip().strip("/")
    if "/" in value:
        value = value.split("/", 1)[0]
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")].strip()
    if value.count(":") == 1:
        host_part, maybe_port = value.rsplit(":", 1)
        if maybe_port.isdigit():
            value = host_part
    return value.strip().lower()


def normalize_reality_target(value: str) -> tuple[str, bool]:
    raw = str(value or "").strip().lower()
    raw = raw.replace("https://", "").replace("http://", "").strip().strip("/")
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if raw.startswith("[") and "]" in raw:
        return raw[1:raw.index("]")].strip(), False
    if raw.count(":") == 1 and raw.rsplit(":", 1)[1].isdigit():
        return raw, True
    return raw, False


_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$")


def is_valid_ip_or_hostname(value: str) -> bool:
    value = normalize_host_value(value)
    if not value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    return bool(_HOSTNAME_RE.match(value)) and "." in value



def parse_imported_vless_link(link: str) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    raw = str(link or "").strip()
    if not raw:
        return {}, ["VLESS 链接不能为空"]
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError as exc:
        return {}, [f"VLESS 链接解析失败：{exc}"]
    if parsed.scheme != "vless" or not parsed.username or not parsed.hostname:
        return {}, ["请粘贴完整 vless:// 链接"]
    host = normalize_host_value(parsed.hostname)
    if not is_valid_ip_or_hostname(host):
        errors.append("VLESS 链接里的地址不是有效 IP 或域名")
    port = parsed.port or 443
    if port <= 0 or port > 65535:
        errors.append("VLESS 链接端口必须在 1-65535 之间")
    remark = urllib.parse.unquote(parsed.fragment or "").strip()
    return {"host": host, "port": port, "remark": remark, "link": raw}, errors



def apply_imported_vless_defaults(cleaned: dict[str, object], link_info: dict[str, object]) -> None:
    cleaned["ip"] = str(link_info.get("host") or "")
    cleaned["ssh_port"] = 22
    cleaned["ssh_user"] = "imported"
    cleaned["ssh_password"] = ""
    cleaned["public_port"] = int(link_info.get("port") or 443)
    cleaned["listen_port"] = int(link_info.get("port") or 443)
    cleaned["front_node_id"] = None
    cleaned["backend_node_id"] = None
    cleaned["chain_mode"] = None
    cleaned["cf_host"] = None
    cleaned["cf_tunnel_token"] = None
    cleaned["ws_port"] = 8080
    cleaned["ws_path"] = "/"
    cleaned["last_vless_link"] = str(link_info.get("link") or "")



def apply_chain_endpoint_defaults(cleaned: dict[str, object], front_node) -> None:
    cleaned["ip"] = front_node["ip"]
    cleaned["ssh_port"] = front_node["ssh_port"]
    cleaned["ssh_user"] = front_node["ssh_user"]
    cleaned["ssh_password"] = front_node["ssh_password"]
    if not str(cleaned.get("public_port") or "").strip():
        cleaned["public_port"] = front_node["public_port"]
    if not str(cleaned.get("listen_port") or "").strip():
        cleaned["listen_port"] = front_node["listen_port"]



def clean_node_form(form: dict[str, str], *, editing_node_id: str | None = None) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    cleaned: dict[str, object] = {}
    if str(form.get("_import_edit_locked") or "") == "1":
        existing = get_node(editing_node_id) if editing_node_id else None
        if not existing or not is_import_protocol(existing["protocol_type"]):
            errors.append("仅导入节点不存在")
        else:
            original = dict(existing)
            cleaned.update(original)
            cleaned["name"] = str(form.get("name") or original.get("name") or "").strip()[:80]
            manual_country_code = str(form.get("manual_country_code") or "").strip().upper()
            manual_region_label = str(form.get("manual_region_label") or "").strip()
            if manual_country_code and (len(manual_country_code) != 2 or not manual_country_code.isalpha()):
                errors.append("国家/地区代码请填写两位字母，例如 JP / HK / US")
            cleaned["manual_country_code"] = manual_country_code or None
            cleaned["manual_region_label"] = manual_region_label or None
            cleaned["protocol_type"] = PROTOCOL_IMPORT
            if not cleaned["name"]:
                errors.append("name 不能为空")
        return cleaned, errors

    protocol_type = str(form.get("protocol_type") or PROTOCOL_DIRECT).strip() or PROTOCOL_DIRECT
    if protocol_type not in {PROTOCOL_DIRECT, PROTOCOL_CHAIN, PROTOCOL_TUNNEL, PROTOCOL_IMPORT}:
        errors.append("protocol_type 不支持")
        protocol_type = PROTOCOL_DIRECT
    cleaned["protocol_type"] = protocol_type

    required_fields = list(REQUIRED_FIELDS)
    if is_chain_protocol(protocol_type):
        for optional_key in ["ip", "ssh_port", "ssh_user", "ssh_password", "public_port", "listen_port"]:
            if optional_key in required_fields:
                required_fields.remove(optional_key)
    if is_tunnel_protocol(protocol_type):
        for optional_key in ["public_port", "listen_port"]:
            if optional_key in required_fields:
                required_fields.remove(optional_key)
    if is_import_protocol(protocol_type):
        for optional_key in ["ip", "ssh_port", "ssh_user", "ssh_password", "public_port", "listen_port"]:
            if optional_key in required_fields:
                required_fields.remove(optional_key)

    for key in required_fields:
        value = str(form.get(key, "")).strip()
        if key == "ip":
            value = normalize_host_value(value)
        if not value:
            errors.append(f"{key} 不能为空")
        cleaned[key] = value

    for key in REQUIRED_FIELDS:
        default_value = str(form.get(key, "")).strip()
        if key == "ip":
            default_value = normalize_host_value(default_value)
        cleaned.setdefault(key, default_value)

    # Tunnel mode does not use NAT public/listen ports. Keep internal safe defaults
    # so DB NOT NULL / integer conversion paths never reject an otherwise valid
    # tunnel node when the hidden/unused inputs are blank.
    if is_tunnel_protocol(protocol_type):
        cleaned["public_port"] = 443
        cleaned["listen_port"] = str(form.get("ws_port") or "8080").strip() or "8080"

    cleaned["front_node_id"] = str(form.get("front_node_id") or "").strip()
    cleaned["backend_node_id"] = str(form.get("backend_node_id") or "").strip()
    cleaned["chain_mode"] = CHAIN_MODE if is_chain_protocol(protocol_type) else None
    manual_country_code = str(form.get("manual_country_code") or "").strip().upper()
    manual_region_label = str(form.get("manual_region_label") or "").strip()
    if manual_country_code and (len(manual_country_code) != 2 or not manual_country_code.isalpha()):
        errors.append("国家/地区代码请填写两位字母，例如 JP / HK / US")
    cleaned["manual_country_code"] = manual_country_code or None
    cleaned["manual_region_label"] = manual_region_label or None
    reality_target, reality_target_has_port = normalize_reality_target(str(form.get("selected_reality_target") or ""))
    if reality_target_has_port:
        errors.append("Reality 伪装目标只填域名，不要带端口；端口固定使用 443")
    if reality_target and not is_valid_ip_or_hostname(reality_target):
        errors.append("Reality 伪装目标请输入有效域名，例如 www.example.com")
    cleaned["selected_reality_target"] = reality_target or "www.example.com"
    cf_host = str(form.get("cf_host") or "").strip().lower().replace("https://", "").replace("http://", "").strip("/")
    cf_tunnel_token = str(form.get("cf_tunnel_token") or "").strip()
    ws_path = str(form.get("ws_path") or "/").strip() or "/"
    if not ws_path.startswith("/"):
        ws_path = f"/{ws_path}"
    cleaned["cf_host"] = cf_host or None
    cleaned["cf_tunnel_token"] = cf_tunnel_token or None
    cleaned["ws_port"] = str(form.get("ws_port") or "8080").strip() or "8080"
    cleaned["ws_path"] = ws_path

    if is_chain_protocol(protocol_type):
        front_node_id = str(cleaned["front_node_id"] or "")
        backend_node_id = str(cleaned["backend_node_id"] or "")
        if not front_node_id:
            errors.append("front_node_id 不能为空")
        if not backend_node_id:
            errors.append("backend_node_id 不能为空")
        if front_node_id and backend_node_id and front_node_id == backend_node_id:
            errors.append("前置节点和后端节点不能相同")

        front_node = get_node(front_node_id) if front_node_id else None
        backend_node = get_node(backend_node_id) if backend_node_id else None
        if front_node_id and not front_node:
            errors.append("前置节点不存在")
        if backend_node_id and not backend_node:
            errors.append("后端节点不存在")
        if front_node and front_node["protocol_type"] != PROTOCOL_DIRECT:
            errors.append("前置节点必须是 VLESS + Reality 直连节点")
        if backend_node and not is_chain_backend_protocol(backend_node["protocol_type"]):
            errors.append("后端节点必须是直连或仅导入 VLESS 节点；tunnel 仅作为单节点使用，不再作为链式落地端")
        if front_node and editing_node_id and front_node["node_id"] == editing_node_id:
            errors.append("链式节点不能选择自己作为前置节点")
        if backend_node and editing_node_id and backend_node["node_id"] == editing_node_id:
            errors.append("链式节点不能选择自己作为后端节点")
        if front_node:
            apply_chain_endpoint_defaults(cleaned, front_node)
    elif is_tunnel_protocol(protocol_type):
        if not cf_host:
            errors.append("应用路由域名不能为空")
        if not cf_tunnel_token:
            errors.append("Tunnel token 不能为空")
        cleaned["front_node_id"] = None
        cleaned["backend_node_id"] = None
        cleaned["chain_mode"] = None
        cleaned["public_port"] = 443
        cleaned["listen_port"] = cleaned["ws_port"]
    elif is_import_protocol(protocol_type):
        link_info, link_errors = parse_imported_vless_link(str(form.get("last_vless_link") or ""))
        errors.extend(link_errors)
        if link_info:
            apply_imported_vless_defaults(cleaned, link_info)
            if not str(cleaned.get("name") or "").strip() and link_info.get("remark"):
                cleaned["name"] = str(link_info["remark"])[:80]
    else:
        cleaned["front_node_id"] = None
        cleaned["backend_node_id"] = None
        cleaned["chain_mode"] = None
        cleaned["cf_host"] = None
        cleaned["cf_tunnel_token"] = None
        cleaned["ws_port"] = 8080
        cleaned["ws_path"] = "/"

    if is_chain_protocol(protocol_type) or is_import_protocol(protocol_type) or is_tunnel_protocol(protocol_type):
        cleaned["selected_reality_target"] = None

    if not is_chain_protocol(protocol_type) and not is_import_protocol(protocol_type):
        host_value = str(cleaned.get("ip") or "").strip()
        if host_value and not is_valid_ip_or_hostname(host_value):
            errors.append("NAT IP 可填写 IP 或 DDNS 域名，例如 203.0.113.10 / node.example.com")

    for int_key in ["ssh_port", "public_port", "listen_port", "ws_port"]:
        value = str(cleaned.get(int_key, ""))
        if value:
            try:
                number = int(value)
                if number <= 0 or number > 65535:
                    errors.append(f"{int_key} 必须在 1-65535 之间")
                else:
                    cleaned[int_key] = number
            except ValueError:
                errors.append(f"{int_key} 必须是数字")

    return cleaned, errors



def protocol_label(protocol_type: object) -> str:
    mapping = {
        PROTOCOL_DIRECT: "vless",
        PROTOCOL_CHAIN: "vless",
        PROTOCOL_TUNNEL: "tunnel",
        PROTOCOL_IMPORT: "import",
        "hy2": "hy2",
        "hysteria2": "hy2",
    }
    return mapping.get(str(protocol_type or ""), str(protocol_type or "-"))


def country_code_to_badge(country_code: str) -> str:
    from .regions import country_code_to_badge as _country_code_to_badge
    return _country_code_to_badge(country_code)


COUNTRY_NAME_MAP = {
    "HK": "香港",
    "JP": "日本",
    "KR": "韩国",
    "US": "美国",
    "TW": "台湾",
    "SG": "新加坡",
    "TR": "土耳其",
    "AU": "澳洲",
    "CN": "中国",
    "MY": "马来西亚",
    "DE": "德国",
    "GB": "英国",
}


def render_node_form(
    request: Request,
    *,
    title: str,
    mode: str,
    form_values: dict[str, object],
    errors: list[str] | None = None,
    node_id: str | None = None,
    form_kind: str = "direct",
):
    front_nodes = [node for node in list_direct_vless_nodes() if node["node_id"] != node_id]
    backend_nodes = [node for node in list_chain_backend_nodes() if node["node_id"] != node_id]
    return templates.TemplateResponse(
        request,
        "node-form.html",
        {
            "request": request,
            "title": title,
            "mode": mode,
            "form_values": form_values,
            "errors": errors or [],
            "node_id": node_id,
            "direct_nodes": front_nodes,
            "front_nodes": front_nodes,
            "backend_nodes": backend_nodes,
            "protocol_direct": PROTOCOL_DIRECT,
            "protocol_chain": PROTOCOL_CHAIN,
            "protocol_tunnel": PROTOCOL_TUNNEL,
            "protocol_import": PROTOCOL_IMPORT,
            "chain_mode": CHAIN_MODE,
            "form_kind": form_kind,
            "is_chain_form": form_kind == "chain" or form_values.get("protocol_type") == PROTOCOL_CHAIN,
            "is_tunnel_form": form_values.get("protocol_type") == PROTOCOL_TUNNEL,
            "is_import_form": form_kind == "import" or form_values.get("protocol_type") == PROTOCOL_IMPORT,
        },
    )



def compute_badge(node) -> tuple[str, str]:
    status = node["status"]
    last_seen_at = node["last_seen_at"]
    if status == "online" and last_seen_at:
        try:
            seen = datetime.fromisoformat(last_seen_at)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - seen > timedelta(minutes=STATUS_STALE_MINUTES):
                return "offline", "离线"
        except ValueError:
            return "offline", "离线"
    mapping = {
        "online": ("online", "在线"),
        "deployed": ("online", "在线"),
        "offline": ("offline", "离线"),
        "failed": ("failed", "部署失败"),
        "deploy_failed": ("failed", "部署失败"),
        "never_deployed": ("pending", "未部署"),
        "deploying": ("pending", "部署中"),
    }
    return mapping.get(status, ("pending", status))


def compute_effective_badge(node, node_by_id: dict[str, object] | None = None) -> tuple[str, str]:
    own_badge = compute_badge(node)
    if node["protocol_type"] != PROTOCOL_CHAIN:
        return own_badge
    if own_badge[0] in {"pending", "failed"}:
        return own_badge
    if not node_by_id:
        return own_badge
    front = node_by_id.get(node["front_node_id"])
    backend = node_by_id.get(node["backend_node_id"])
    if not front or not backend:
        return "offline", "离线"
    if compute_badge(front)[0] != "online" or compute_badge(backend)[0] != "online":
        return "offline", "离线"
    return "online", "在线"



def build_install_command(node: dict | object) -> str:
    if isinstance(node, dict):
        node_id = node["node_id"]
        ip = node["ip"]
        ssh_port = node["ssh_port"]
        public_port = node["public_port"]
        listen_port = node["listen_port"]
    else:
        node_id = node["node_id"]
        ip = node["ip"]
        ssh_port = node["ssh_port"]
        public_port = node["public_port"]
        listen_port = node["listen_port"]
    return (
        f"ssh <user>@{ip} -p {ssh_port} '"
        f"echo deploy-node {node_id} public:{public_port} listen:{listen_port}'"
    )



SUBSCRIPTION_SCOPES = {
    "all": None,
    "direct": (PROTOCOL_DIRECT, PROTOCOL_TUNNEL),
    "chain": PROTOCOL_CHAIN,
    "imported": PROTOCOL_IMPORT,
}


def mask_ip_for_list(ip_value: str | None) -> str:
    value = str(ip_value or "")
    if not value:
        return ""
    if ":" in value:
        parts = value.split(":")
        if len(parts) <= 2:
            return value[:2] + "***"
        return ":".join(parts[:2] + ["****"] + parts[-1:])
    parts = value.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.{parts[3]}"
    if len(value) <= 6:
        return value[0:1] + "***"
    return value[:3] + "***" + value[-2:]


def normalize_subscription_scope(scope: str | None) -> str:
    scope = (scope or "all").strip().lower()
    aliases = {
        "import": "imported",
        "imports": "imported",
        "imported_vless": "imported",
    }
    scope = aliases.get(scope, scope)
    return scope if scope in SUBSCRIPTION_SCOPES else "all"


def subscription_filename(scope: str, kind: str) -> str:
    prefix = "nat" if scope == "all" else f"nat-{scope}"
    suffix = "clash.yaml" if kind == "clash" else "subscription.txt"
    return f"{prefix}-{suffix}"


def build_subscription_url(request: Request, scope: str = "all") -> str:
    token = get_or_create_subscription_token()
    return str(request.url_for("subscription_feed", token=token).include_query_params(scope=normalize_subscription_scope(scope)))


def build_clash_subscription_url(request: Request, scope: str = "all") -> str:
    token = get_or_create_subscription_token()
    return str(request.url_for("clash_subscription_feed", token=token).include_query_params(scope=normalize_subscription_scope(scope)))




def display_protocol_label(protocol_type: str | None) -> str:
    if protocol_type == PROTOCOL_TUNNEL:
        return "tunnel"
    if protocol_type == PROTOCOL_CHAIN:
        return "chain"
    if protocol_type == PROTOCOL_IMPORT:
        return "import"
    return "vless"


def vless_link_with_node_remark(link: str, node: sqlite3.Row | dict[str, object], *, region_source_node: sqlite3.Row | dict[str, object] | None = None) -> str:
    return replace_vless_fragment(link, vless_remark_for_node(node, allow_lookup=True, region_source_node=region_source_node))


def build_tunnel_vless_link(node: sqlite3.Row | dict[str, object], *, generated_uuid: str | None = None, region_source_node: sqlite3.Row | dict[str, object] | None = None) -> str:
    cf_host = str(node["cf_host"] or "").strip().strip("/")
    if not cf_host:
        return ""
    uuid_value = (generated_uuid or str(node["generated_uuid"] or "")).strip()
    if not uuid_value:
        return ""
    ws_path = str(node["ws_path"] or "/").strip() or "/"
    if not ws_path.startswith("/"):
        ws_path = f"/{ws_path}"
    name = urllib.parse.quote(vless_remark_for_node(node, allow_lookup=True, region_source_node=region_source_node), safe="")
    query = urllib.parse.urlencode(
        {
            "encryption": "none",
            "security": "tls",
            "type": "ws",
            "host": cf_host,
            "path": ws_path,
            "sni": cf_host,
        }
    )
    return f"vless://{uuid_value}@{cf_host}:443?{query}#{name}"


def display_vless_link_for_node(node: sqlite3.Row | dict[str, object], node_by_id: dict[str, sqlite3.Row | dict[str, object]] | None = None) -> str:
    region_source_node = None
    if str(node["protocol_type"] or "") == PROTOCOL_CHAIN and node_by_id:
        region_source_node = node_by_id.get(str(node["backend_node_id"] or ""))
    if is_tunnel_protocol(str(node["protocol_type"] or "")):
        link = build_tunnel_vless_link(node, region_source_node=region_source_node)
        if link:
            return link
    return vless_link_with_node_remark(str(node["last_vless_link"] or ""), node, region_source_node=region_source_node)

def build_subscription_payload(scope: str = "all") -> str:
    protocol_type = SUBSCRIPTION_SCOPES[normalize_subscription_scope(scope)]
    nodes = list_subscribable_nodes(protocol_type)
    all_nodes = list_nodes()
    node_by_id = {node["node_id"]: node for node in all_nodes}
    links = []
    for node in nodes:
        link = display_vless_link_for_node(node, node_by_id).strip()
        if link:
            links.append(link)
    plain = "\n".join(links)
    return base64.b64encode(plain.encode("utf-8")).decode("ascii")


def _query_first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key) or []
    return values[0] if values else default


def _vless_link_to_clash_proxy(link: str) -> dict[str, object] | None:
    try:
        parsed = urllib.parse.urlparse(link)
    except ValueError:
        return None
    if parsed.scheme != "vless" or not parsed.hostname or not parsed.username:
        return None
    query = urllib.parse.parse_qs(parsed.query)
    name = urllib.parse.unquote(parsed.fragment or parsed.hostname)
    sni = _query_first(query, "sni") or _query_first(query, "peer")
    public_key = _query_first(query, "pbk")
    short_id = _query_first(query, "sid")
    proxy: dict[str, object] = {
        "name": name,
        "type": "vless",
        "server": parsed.hostname,
        "port": parsed.port or 443,
        "uuid": urllib.parse.unquote(parsed.username),
        "network": _query_first(query, "type", "tcp") or "tcp",
        "udp": True,
        "tls": True,
        "servername": sni,
        "flow": _query_first(query, "flow", "xtls-rprx-vision") or "xtls-rprx-vision",
        "client-fingerprint": _query_first(query, "fp", "chrome") or "chrome",
        "reality-opts": {
            "public-key": public_key,
            "short-id": short_id,
        },
    }
    if _query_first(query, "spx"):
        proxy["reality-opts"]["spider-x"] = _query_first(query, "spx")  # type: ignore[index]
    return proxy


def build_clash_subscription_payload(scope: str = "all") -> str:
    protocol_type = SUBSCRIPTION_SCOPES[normalize_subscription_scope(scope)]
    nodes = list_subscribable_nodes(protocol_type)
    all_nodes = list_nodes()
    node_by_id = {node["node_id"]: node for node in all_nodes}
    proxies = []
    seen_names: set[str] = set()
    for node in nodes:
        link = display_vless_link_for_node(node, node_by_id).strip()
        if not link:
            continue
        proxy = _vless_link_to_clash_proxy(link)
        if not proxy:
            continue
        base_name = str(proxy["name"])
        name = base_name
        idx = 2
        while name in seen_names:
            name = f"{base_name}-{idx}"
            idx += 1
        proxy["name"] = name
        seen_names.add(name)
        proxies.append(proxy)
    names = [str(p["name"]) for p in proxies]
    payload = {
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "NAT-WebUI",
                "type": "select",
                "proxies": names + ["DIRECT"],
            }
        ],
        "rules": ["MATCH,NAT-WebUI"],
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)



@app.get("/nodes", response_class=HTMLResponse)
@login_required
async def nodes_page(request: Request):
    raw_nodes = list_nodes()
    node_by_id = {node["node_id"]: node for node in raw_nodes}
    tag_map = list_node_tags_map()
    region_cache: dict[str, dict[str, str]] = {}
    nodes = []
    for node in raw_nodes:
        badge_class, badge_text = compute_effective_badge(node, node_by_id)
        if node["protocol_type"] == PROTOCOL_CHAIN:
            backend = node_by_id.get(node["backend_node_id"])
            region = region_from_node(backend, allow_lookup=True) if backend else {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": "落地端未知"}
            if region.get("label"):
                region = {**region, "label": f"落地端：{region.get('label')}"}
        else:
            region = region_from_node(node, allow_lookup=True)
        is_chain = bool(node["protocol_type"] == PROTOCOL_CHAIN)
        masked_ip = mask_ip_for_list(node["ip"])
        masked_entry_text = (
            f"{node['front_node_name'] or node['front_node_id']} → {node['backend_node_name'] or node['backend_node_id']}"
            if is_chain
            else masked_ip
        )
        nodes.append({
            "node_id": node["node_id"],
            "name": node["name"],
            "ip": node["ip"],
            "masked_ip": masked_ip,
            "masked_entry_text": masked_entry_text,
            "protocol_type": node["protocol_type"],
            "protocol_label": protocol_label(node["protocol_type"]),
            "region_flag": region.get("flag", ""),
            "region_flag_codes": region.get("flag_codes", []),
            "region_badge": region.get("badge", "") or region.get("code", ""),
            "region_code": region.get("code", ""),
            "region_label": region.get("label", ""),
            "front_node_id": node["front_node_id"],
            "backend_node_id": node["backend_node_id"],
            "front_node_name": node["front_node_name"],
            "backend_node_name": node["backend_node_name"],
            "badge_class": badge_class,
            "badge_text": badge_text,
            "last_vless_link": display_vless_link_for_node(node, node_by_id),
            "tags": tag_map.get(node["node_id"], []),
            "can_reinstall": node["protocol_type"] != PROTOCOL_IMPORT,
            "is_chain": is_chain,
        })
    direct_nodes = [node for node in nodes if node["protocol_type"] in {PROTOCOL_DIRECT, PROTOCOL_TUNNEL}]
    chain_nodes = [node for node in nodes if node["is_chain"]]
    import_nodes = [node for node in nodes if node["protocol_type"] == PROTOCOL_IMPORT]
    subscription_urls = {
        "all": {"v2rayn": build_subscription_url(request), "clash": build_clash_subscription_url(request)},
        "direct": {"v2rayn": build_subscription_url(request, "direct"), "clash": build_clash_subscription_url(request, "direct")},
        "chain": {"v2rayn": build_subscription_url(request, "chain"), "clash": build_clash_subscription_url(request, "chain")},
        "imported": {"v2rayn": build_subscription_url(request, "imported"), "clash": build_clash_subscription_url(request, "imported")},
    }
    return templates.TemplateResponse(
        request,
        "nodes.html",
        {
            "request": request,
            "title": "节点列表",
            "nodes": nodes,
            "direct_nodes": direct_nodes,
            "chain_nodes": chain_nodes,
            "import_nodes": import_nodes,
            "subscription_url": subscription_urls["all"]["v2rayn"],
            "clash_subscription_url": subscription_urls["all"]["clash"],
            "subscription_urls": subscription_urls,
            "subscription_state": get_subscription_token_state(),
            "tags": list_tags(),
            "tag_colors": TAG_COLORS,
        },
    )


@app.post("/subscriptions/rotate-token")
@login_required
async def rotate_subscription_token_action(request: Request):
    token_state = rotate_subscription_token()
    new_token = token_state["subscription_token"]
    subscription_urls = {
        "all": {"v2rayn": str(request.url_for("subscription_feed", token=new_token).include_query_params(scope="all")), "clash": str(request.url_for("clash_subscription_feed", token=new_token).include_query_params(scope="all"))},
        "direct": {"v2rayn": str(request.url_for("subscription_feed", token=new_token).include_query_params(scope="direct")), "clash": str(request.url_for("clash_subscription_feed", token=new_token).include_query_params(scope="direct"))},
        "chain": {"v2rayn": str(request.url_for("subscription_feed", token=new_token).include_query_params(scope="chain")), "clash": str(request.url_for("clash_subscription_feed", token=new_token).include_query_params(scope="chain"))},
        "imported": {"v2rayn": str(request.url_for("subscription_feed", token=new_token).include_query_params(scope="imported")), "clash": str(request.url_for("clash_subscription_feed", token=new_token).include_query_params(scope="imported"))},
    }
    return JSONResponse({
        "ok": True,
        "subscription_token": new_token,
        "previous_expires_at": token_state["previous_expires_at"],
        "subscription_urls": subscription_urls,
        "message": "订阅 token 已轮换。旧 token 将继续保留 24 小时可用，请尽快把客户端订阅更新为新链接。",
    })


@app.get("/sub/{token}", response_class=PlainTextResponse, name="subscription_feed")
async def subscription_feed(token: str, scope: str = "all"):
    if not validate_subscription_token(token):
        return PlainTextResponse("forbidden", status_code=403)
    scope = normalize_subscription_scope(scope)
    payload = build_subscription_payload(scope)
    return PlainTextResponse(
        payload,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{subscription_filename(scope, "v2rayn")}"',
        },
    )


@app.get("/sub/{token}/clash", response_class=PlainTextResponse, name="clash_subscription_feed")
async def clash_subscription_feed(token: str, scope: str = "all"):
    if not validate_subscription_token(token):
        return PlainTextResponse("forbidden", status_code=403)
    scope = normalize_subscription_scope(scope)
    payload = build_clash_subscription_payload(scope)
    return PlainTextResponse(
        payload,
        media_type="text/yaml; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{subscription_filename(scope, "clash")}"',
        },
    )


@app.get("/nodes/new", response_class=HTMLResponse)
@login_required
async def node_create_page(request: Request):
    values = default_form_values()
    values["protocol_type"] = PROTOCOL_DIRECT
    return render_node_form(
        request,
        title="新建节点",
        mode="create",
        form_values=values,
        form_kind="direct",
    )


@app.get("/nodes/new-chain", response_class=HTMLResponse)
@login_required
async def chain_node_create_page(request: Request):
    values = default_form_values()
    values["protocol_type"] = PROTOCOL_CHAIN
    return render_node_form(
        request,
        title="新建链式节点",
        mode="create",
        form_values=values,
        form_kind="chain",
    )


@app.get("/nodes/import", response_class=HTMLResponse)
@login_required
async def import_nodes_page(request: Request):
    return templates.TemplateResponse(
        request,
        "import-form.html",
        {
            "request": request,
            "title": "导入节点",
        },
    )


@app.get("/nodes/new-import", response_class=HTMLResponse)
@login_required
async def import_node_create_page(request: Request):
    values = default_form_values()
    values["protocol_type"] = PROTOCOL_IMPORT
    values["ssh_user"] = "imported"
    return render_node_form(
        request,
        title="导入节点",
        mode="create",
        form_values=values,
        form_kind="import",
    )


@app.post("/nodes/new", response_class=HTMLResponse)
@login_required
async def node_create_submit(
    request: Request,
    name: str = Form(...),
    ip: str = Form(""),
    ssh_port: str = Form(""),
    ssh_user: str = Form(""),
    ssh_password: str = Form(""),
    public_port: str = Form(""),
    listen_port: str = Form(""),
    protocol_type: str = Form(PROTOCOL_DIRECT),
    selected_reality_target: str = Form(""),
    cf_host: str = Form(""),
    cf_tunnel_token: str = Form(""),
    ws_port: str = Form("8080"),
    ws_path: str = Form("/"),
    front_node_id: str = Form(""),
    backend_node_id: str = Form(""),
    manual_country_code: str = Form(""),
    manual_region_label: str = Form(""),
    last_vless_link: str = Form(""),
):
    payload, errors = clean_node_form(
        {
            "name": name,
            "ip": ip,
            "ssh_port": ssh_port,
            "ssh_user": ssh_user,
            "ssh_password": ssh_password,
            "public_port": public_port,
            "listen_port": listen_port,
            "protocol_type": protocol_type,
            "selected_reality_target": selected_reality_target,
            "cf_host": cf_host,
            "cf_tunnel_token": cf_tunnel_token,
            "ws_port": ws_port,
            "ws_path": ws_path,
            "front_node_id": front_node_id,
            "backend_node_id": backend_node_id,
            "manual_country_code": manual_country_code,
            "manual_region_label": manual_region_label,
            "last_vless_link": last_vless_link,
        }
    )

    if not errors and is_direct_vless_protocol(payload.get("protocol_type")):
        conflict = find_direct_vless_port_conflict(
            str(payload["ip"]),
            int(payload["public_port"]),
            int(payload["listen_port"]),
        )
        if conflict:
            errors.append("已存在相同 IP + 公网端口或监听端口 的节点记录")

    if errors:
        return render_node_form(
            request,
            title=("新建链式节点" if is_chain_protocol(payload.get("protocol_type")) else ("导入节点" if is_import_protocol(payload.get("protocol_type")) else "新建节点")),
            mode="create",
            form_values=payload,
            errors=errors,
            form_kind=("chain" if is_chain_protocol(payload.get("protocol_type")) else ("import" if is_import_protocol(payload.get("protocol_type")) else "direct")),
        )

    node_id = create_node_record(payload)
    return RedirectResponse(url=f"/nodes/{node_id}", status_code=303)


@app.post("/nodes/import", response_class=HTMLResponse)
@login_required
async def import_nodes_action(request: Request):
    form = await request.form()
    text = str(form.get("links") or "").strip()
    if not text:
        return PlainTextResponse("请输入至少一个 VLESS 链接", status_code=400)

    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    created_count = 0
    skipped_count = 0
    errors_list: list[str] = []

    for line in lines:
        link_info, link_errors = parse_imported_vless_link(line)
        if link_errors:
            skipped_count += 1
            errors_list.extend(link_errors)
            continue
        name = str(link_info.get("remark") or "").strip() or f"导入-{link_info.get('host')}:{link_info.get('port')}"
        payload = {
            "name": name[:80],
            "ip": "",
            "ssh_port": "",
            "ssh_user": "imported",
            "ssh_password": "",
            "public_port": "",
            "listen_port": "",
            "protocol_type": PROTOCOL_IMPORT,
            "last_vless_link": line,
            "manual_country_code": "",
            "manual_region_label": "",
        }
        payload, errors = clean_node_form(payload)
        if errors:
            skipped_count += 1
            errors_list.extend(f"{name}: {error}" for error in errors)
            continue
        try:
            create_node_record(payload)
            created_count += 1
        except Exception as exc:
            skipped_count += 1
            errors_list.append(f"{name}: {exc}")

    return templates.TemplateResponse(
        request,
        "import-form.html",
        {
            "request": request,
            "title": "导入节点",
            "result": {
                "created": created_count,
                "skipped": skipped_count,
                "errors": errors_list,
            },
        },
    )


@app.post("/nodes/new-import", response_class=HTMLResponse)
@login_required
async def import_node_create_submit(
    request: Request,
    name: str = Form(""),
    last_vless_link: str = Form(""),
    manual_country_code: str = Form(""),
    manual_region_label: str = Form(""),
):
    payload, errors = clean_node_form(
        {
            "name": name,
            "ip": "",
            "ssh_port": "",
            "ssh_user": "imported",
            "ssh_password": "",
            "public_port": "",
            "listen_port": "",
            "protocol_type": PROTOCOL_IMPORT,
            "last_vless_link": last_vless_link,
            "manual_country_code": manual_country_code,
            "manual_region_label": manual_region_label,
        }
    )
    if errors:
        return render_node_form(
            request,
            title="导入节点",
            mode="create",
            form_values=payload,
            errors=errors,
            form_kind="import",
        )
    node_id = create_node_record(payload)
    return RedirectResponse(url=f"/nodes/{node_id}", status_code=303)


@app.post("/nodes/new-chain", response_class=HTMLResponse)
@login_required
async def chain_node_create_submit(
    request: Request,
    name: str = Form(...),
    front_node_id: str = Form(""),
    backend_node_id: str = Form(""),
    public_port: str = Form(""),
    listen_port: str = Form(""),
):
    payload, errors = clean_node_form(
        {
            "name": name,
            "ip": "",
            "ssh_port": "",
            "ssh_user": "",
            "ssh_password": "",
            "public_port": public_port,
            "listen_port": listen_port,
            "protocol_type": PROTOCOL_CHAIN,
            "front_node_id": front_node_id,
            "backend_node_id": backend_node_id,
        }
    )

    if errors:
        return render_node_form(
            request,
            title="新建链式节点",
            mode="create",
            form_values=payload,
            errors=errors,
            form_kind="chain",
        )

    node_id = create_node_record(payload)
    return RedirectResponse(url=f"/nodes/{node_id}", status_code=303)


def build_chain_link(chain_node: dict[str, object], front_node: dict[str, object], backend_node: dict[str, object], chain_uuid: str) -> str:
    raw_backend_name = str(backend_node.get("name") or "backend")
    label = f"{chain_node.get('name') or 'chain'} via {front_node.get('name') or 'front'} -> {raw_backend_name}"
    params = {
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "security": "reality",
        "sni": front_node.get("selected_reality_target") or "www.example.com",
        "fp": "chrome",
        "pbk": front_node.get("generated_public_key") or "",
        "sid": front_node.get("generated_short_id") or "",
        "type": "tcp",
        "headerType": "none",
    }
    query = urllib.parse.urlencode(params)
    return f"vless://{chain_uuid}@{front_node['ip']}:{front_node['public_port']}?{query}#{urllib.parse.quote(label)}"


def generate_chain_deployment(chain_node_id: str) -> tuple[str, str, str, dict[str, object]]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        chain = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (chain_node_id,)).fetchone()
        if not chain:
            raise ValueError("链式节点不存在")
        if chain["protocol_type"] != PROTOCOL_CHAIN:
            raise ValueError("不是链式节点")
        front = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (chain["front_node_id"],)).fetchone()
        backend = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (chain["backend_node_id"],)).fetchone()
        if not front or not backend:
            raise ValueError("前置节点或后端节点不存在")
        if not front["last_vless_link"] or not front["generated_public_key"] or not front["generated_short_id"]:
            raise ValueError("前置节点还没有成功部署链接，不能生成链式入口")
        if not backend["last_vless_link"] or not backend["generated_uuid"]:
            raise ValueError("后端节点还没有成功部署链接，不能生成链式节点")
        if backend["protocol_type"] == PROTOCOL_DIRECT and (not backend["generated_public_key"] or not backend["generated_short_id"]):
            raise ValueError("Reality 后端节点还没有完整 Reality 参数，不能生成链式节点")
        if backend["protocol_type"] == PROTOCOL_TUNNEL:
            raise ValueError("tunnel 节点仅作为单节点使用，不支持作为链式落地端")
        if backend["protocol_type"] != PROTOCOL_DIRECT:
            raise ValueError("后端节点协议不支持链式落地，仅支持 VLESS + Reality")

        chain_uuid = chain["generated_uuid"] or str(uuid.uuid4())
        link = build_chain_link(dict(chain), dict(front), dict(backend), chain_uuid)
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE nodes
            SET ip = ?, ssh_port = ?, ssh_user = ?, ssh_password = ?,
                public_port = ?, listen_port = ?, generated_uuid = ?,
                selected_reality_target = ?, generated_public_key = ?, generated_short_id = ?,
                last_vless_link = ?, status = ?, updated_at = ?
            WHERE node_id = ?
            """,
            (
                front["ip"],
                front["ssh_port"],
                front["ssh_user"],
                front["ssh_password"],
                front["public_port"],
                front["listen_port"],
                chain_uuid,
                front["selected_reality_target"],
                front["generated_public_key"],
                front["generated_short_id"],
                link,
                "deployed",
                ts,
                chain_node_id,
            ),
        )
        chain_tag = f"chain-{chain_node_id}"
        apply_log = apply_front_chain_config(dict(front), dict(backend), chain_tag=chain_tag, chain_uuid=chain_uuid)
        backend_target = f"{backend['ip']}:{backend['public_port']}"
        backend_protocol = "reality"
        summary = f"链式节点已真实下发：前置 {front['name']} 入口 {front['ip']}:{front['public_port']}，按链式用户路由到后端 {backend['name']}（{backend_protocol} {backend_target}）。"
        raw = "\n".join(
            [
                "[stage] chain-route-apply",
                f"front_node={front['name']} {front['ip']}:{front['public_port']}",
                f"backend_node={backend['name']} {backend_protocol} {backend_target}",
                f"chain_tag={chain_tag}",
                f"chain_uuid={chain_uuid}",
                apply_log,
            ]
        )
        return summary, raw, link, {"chain_uuid": chain_uuid, "chain_tag": chain_tag}


def mark_chain_deployment_success(deploy_id: str, summary: str, raw: str, link: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        deployment = conn.execute("SELECT node_id FROM deployments WHERE deploy_id = ?", (deploy_id,)).fetchone()
        if not deployment:
            return
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE deployments
            SET ended_at = ?, result = ?, failure_stage = ?, summary_log = ?, raw_log = ?, generated_vless_link = ?
            WHERE deploy_id = ?
            """,
            (ts, "success", None, redact_sensitive_text(summary), redact_sensitive_text(raw), redact_sensitive_text(link), deploy_id),
        )
        conn.execute("UPDATE nodes SET status = ?, updated_at = ? WHERE node_id = ?", ("deployed", ts, deployment[0]))


def mark_chain_deployment_failed(deploy_id: str, message: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        deployment = conn.execute("SELECT node_id FROM deployments WHERE deploy_id = ?", (deploy_id,)).fetchone()
        if not deployment:
            return
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE deployments
            SET ended_at = ?, result = ?, failure_stage = ?, summary_log = ?, raw_log = ?
            WHERE deploy_id = ?
            """,
            (ts, "failed", "chain_generate", redact_sensitive_text(message), redact_sensitive_text(f"[error] {message}"), deploy_id),
        )
        conn.execute("UPDATE nodes SET status = ?, updated_at = ? WHERE node_id = ?", ("failed", ts, deployment[0]))


@app.get("/nodes/{node_id}", response_class=HTMLResponse)
@login_required
async def node_detail_page(request: Request, node_id: str):
    node = get_node(node_id)
    if not node:
        return templates.TemplateResponse(
            request,
            "not-found.html",
            {"request": request, "title": "未找到节点", "message": "节点不存在"},
            status_code=404,
        )

    deployments = list_deployments_for_node(node_id)
    raw_nodes = list_nodes()
    node_by_id = {item["node_id"]: item for item in raw_nodes}
    badge_class, badge_text = compute_effective_badge(node, node_by_id)
    report = None
    if node["last_report_json"]:
        try:
            report = json.loads(node["last_report_json"])
        except json.JSONDecodeError:
            report = {"raw": node["last_report_json"]}

    latest_deploy_id = deployments[0]["deploy_id"] if deployments else None

    return templates.TemplateResponse(
        request,
        "node-detail.html",
        {
            "request": request,
            "title": node["name"],
            "node": node,
            "display_vless_link": display_vless_link_for_node(node, node_by_id),
            "deployments": deployments,
            "badge_class": badge_class,
            "badge_text": badge_text,
            "report": report,
            "latest_deploy_id": latest_deploy_id,
            "is_chain": bool(node["protocol_type"] == PROTOCOL_CHAIN),
            "is_tunnel": bool(node["protocol_type"] == PROTOCOL_TUNNEL),
            "is_import": bool(node["protocol_type"] == PROTOCOL_IMPORT),
            "protocol_label": protocol_label(node["protocol_type"]),
            "node_tags": tag_map.get(node_id, []) if (tag_map := list_node_tags_map()) else [],
        },
    )


@app.get("/nodes/{node_id}/edit", response_class=HTMLResponse)
@login_required
async def node_edit_page(request: Request, node_id: str):
    node = get_node(node_id)
    if not node:
        return templates.TemplateResponse(
            request,
            "not-found.html",
            {"request": request, "title": "未找到节点", "message": "节点不存在"},
            status_code=404,
        )

    return render_node_form(
        request,
        title=f"编辑节点 · {node['name']}",
        mode="edit",
        node_id=node_id,
        form_values=node_to_form_values(node),
        form_kind=("chain" if node["protocol_type"] == PROTOCOL_CHAIN else ("import" if node["protocol_type"] == PROTOCOL_IMPORT else "direct")),
    )


@app.post("/nodes/{node_id}/edit", response_class=HTMLResponse)
@login_required
async def node_edit_submit(
    request: Request,
    node_id: str,
    name: str = Form(...),
    ip: str = Form(""),
    ssh_port: str = Form(""),
    ssh_user: str = Form(""),
    ssh_password: str = Form(""),
    public_port: str = Form(""),
    listen_port: str = Form(""),
    protocol_type: str = Form(PROTOCOL_DIRECT),
    selected_reality_target: str = Form(""),
    cf_host: str = Form(""),
    cf_tunnel_token: str = Form(""),
    ws_port: str = Form("8080"),
    ws_path: str = Form("/"),
    front_node_id: str = Form(""),
    backend_node_id: str = Form(""),
    manual_country_code: str = Form(""),
    manual_region_label: str = Form(""),
    last_vless_link: str = Form(""),
):
    node = get_node(node_id)
    if not node:
        return templates.TemplateResponse(
            request,
            "not-found.html",
            {"request": request, "title": "未找到节点", "message": "节点不存在"},
            status_code=404,
        )

    payload, errors = clean_node_form(
        {
            "name": name,
            "ip": ip,
            "ssh_port": ssh_port,
            "ssh_user": ssh_user,
            "ssh_password": ssh_password,
            "public_port": public_port,
            "listen_port": listen_port,
            "protocol_type": protocol_type,
            "selected_reality_target": selected_reality_target,
            "cf_host": cf_host,
            "cf_tunnel_token": cf_tunnel_token,
            "ws_port": ws_port,
            "ws_path": ws_path,
            "front_node_id": front_node_id,
            "backend_node_id": backend_node_id,
            "manual_country_code": manual_country_code,
            "manual_region_label": manual_region_label,
            "last_vless_link": last_vless_link,
        },
        editing_node_id=node_id,
    )

    if not errors and is_direct_vless_protocol(payload.get("protocol_type")):
        conflict = find_direct_vless_port_conflict(
            str(payload["ip"]),
            int(payload["public_port"]),
            int(payload["listen_port"]),
            exclude_node_id=node_id,
        )
        if conflict:
            errors.append("已存在相同 IP + 公网端口或监听端口 的节点记录")

    if errors:
        return render_node_form(
            request,
            title=f"编辑节点 · {node['name']}",
            mode="edit",
            node_id=node_id,
            form_values=payload,
            errors=errors,
            form_kind=("chain" if is_chain_protocol(payload.get("protocol_type")) else ("import" if is_import_protocol(payload.get("protocol_type")) else "direct")),
        )

    if is_tunnel_protocol(payload.get("protocol_type")):
        existing = dict(node)
        existing.update(payload)
        payload["last_vless_link"] = build_tunnel_vless_link(existing) or str(node["last_vless_link"] or "")
    elif is_import_protocol(payload.get("protocol_type")):
        payload["last_vless_link"] = str(node["last_vless_link"] or payload.get("last_vless_link") or "")
    else:
        existing = dict(node)
        existing.update(payload)
        payload["last_vless_link"] = vless_link_with_node_remark(str(node["last_vless_link"] or ""), existing)
    update_node_record(node_id, payload)
    return RedirectResponse(url=f"/nodes/{node_id}", status_code=303)


@app.post("/tags")
@login_required
async def tag_create_submit(request: Request, name: str = Form(...), color: str = Form(TAG_COLORS[0])):
    name = name.strip()
    color = color.strip() or TAG_COLORS[0]
    if name:
        try:
            create_tag(name, color)
        except Exception:
            pass
    return RedirectResponse(url="/nodes", status_code=303)


@app.post("/tags/{tag_id}/delete")
@login_required
async def tag_delete_submit(request: Request, tag_id: str):
    delete_tag(tag_id)
    return RedirectResponse(url="/nodes", status_code=303)


@app.post("/nodes/{node_id}/rename")
@login_required
async def node_rename_submit(request: Request, node_id: str, name: str = Form(...), return_to: str = Form("/nodes")):
    new_name = name.strip()
    if get_node(node_id) and new_name:
        rename_node_record(node_id, new_name[:80])
    return RedirectResponse(url=return_to or "/nodes", status_code=303)


@app.post("/nodes/{node_id}/tags")
@login_required
async def node_tags_submit(request: Request, node_id: str, tag_ids: list[str] = Form([]), return_to: str = Form("/nodes")):
    if get_node(node_id):
        set_node_tags(node_id, tag_ids)
    return RedirectResponse(url=return_to or "/nodes", status_code=303)


@app.post("/nodes/{node_id}/reinstall")
@login_required
async def node_reinstall_submit(request: Request, node_id: str):
    node = get_node(node_id)
    if not node:
        return templates.TemplateResponse(
            request,
            "not-found.html",
            {"request": request, "title": "未找到节点", "message": "节点不存在"},
            status_code=404,
        )

    deploy_id = create_deployment_record(node_id=node_id, action_type="chain_generate" if node["protocol_type"] == PROTOCOL_CHAIN else "reinstall")
    if node["protocol_type"] == PROTOCOL_CHAIN:
        try:
            summary, raw, link, _meta = generate_chain_deployment(node_id)
            mark_chain_deployment_success(deploy_id, summary, raw, link)
        except ValueError as exc:
            mark_chain_deployment_failed(deploy_id, str(exc))
        return RedirectResponse(url=f"/deployments/{deploy_id}", status_code=303)

    submit_reinstall_job(deploy_id=deploy_id, node=dict(node))
    return RedirectResponse(url=f"/deployments/{deploy_id}", status_code=303)


@app.get("/deployments/{deploy_id}", response_class=HTMLResponse)
@login_required
async def deployment_detail_page(request: Request, deploy_id: str):
    deployment = get_deployment(deploy_id)
    if not deployment:
        return templates.TemplateResponse(
            request,
            "not-found.html",
            {"request": request, "title": "未找到任务", "message": "部署任务不存在"},
            status_code=404,
        )

    node = get_node(deployment["node_id"])
    return templates.TemplateResponse(
        request,
        "deployment-detail.html",
        {
            "request": request,
            "title": f"部署任务 · {deploy_id}",
            "deployment": deployment,
            "node": node,
            "auto_refresh": deployment["result"] in {"pending", "running"} or is_deploy_running(deploy_id),
        },
    )


@app.get("/api/deployments/{deploy_id}")
@login_required
async def deployment_status_api(request: Request, deploy_id: str):
    deployment = get_deployment(deploy_id)
    if not deployment:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse(
        {
            "deploy_id": deployment["deploy_id"],
            "node_id": deployment["node_id"],
            "result": deployment["result"],
            "failure_stage": deployment["failure_stage"],
            "summary_log": deployment["summary_log"],
            "raw_log": deployment["raw_log"],
            "generated_vless_link": deployment["generated_vless_link"],
            "started_at": deployment["started_at"],
            "ended_at": deployment["ended_at"],
            "running": is_deploy_running(deploy_id),
        }
    )


@app.post("/nodes/{node_id}/delete")
@login_required
async def node_delete_submit(request: Request, node_id: str, return_to: str = Query("/nodes")):
    node = get_node(node_id)
    if not node:
        return RedirectResponse(url=return_to or "/nodes", status_code=303)
    delete_node_record(node_id)
    return RedirectResponse(url=return_to or "/nodes", status_code=303)
