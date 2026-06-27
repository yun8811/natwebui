import json
import os
import shlex
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RemoteApplyError(RuntimeError):
    pass


def _run(cmd: list[str], *, timeout: int = 60, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    if input_text is not None:
        return subprocess.run(cmd, input=input_text, text=True, capture_output=True, timeout=timeout)
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


def _ssh_base(node: dict[str, Any]) -> list[str]:
    return [
        "sshpass",
        "-p",
        str(node["ssh_password"]),
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
        "-p",
        str(node["ssh_port"]),
        f"{node['ssh_user']}@{node['ip']}",
    ]


def _scp_to(node: dict[str, Any], local_path: str, remote_path: str) -> None:
    cmd = [
        "sshpass",
        "-p",
        str(node["ssh_password"]),
        "scp",
        "-P",
        str(node["ssh_port"]),
        "-o",
        "StrictHostKeyChecking=no",
        local_path,
        f"{node['ssh_user']}@{node['ip']}:{remote_path}",
    ]
    proc = _run(cmd, timeout=60)
    if proc.returncode != 0:
        raise RemoteApplyError(f"scp failed: {proc.stderr or proc.stdout}")


def _ssh(node: dict[str, Any], script: str, *, timeout: int = 60) -> str:
    proc = _run(_ssh_base(node) + [script], timeout=timeout)
    if proc.returncode != 0:
        raise RemoteApplyError(proc.stderr or proc.stdout or f"ssh command failed: {script}")
    return proc.stdout


def fetch_remote_singbox_config(node: dict[str, Any]) -> dict[str, Any]:
    data = _ssh(node, "cat /etc/sing-box/config.json", timeout=30)
    return json.loads(data)


def _find_vless_inbound(config: dict[str, Any]) -> dict[str, Any]:
    for inbound in config.get("inbounds", []):
        if inbound.get("type") == "vless" and inbound.get("tls", {}).get("reality", {}).get("enabled"):
            return inbound
    raise RemoteApplyError("front sing-box Reality VLESS inbound not found")


def _upsert_by_tag(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    tag = item.get("tag")
    for idx, old in enumerate(items):
        if old.get("tag") == tag:
            items[idx] = item
            return
    items.append(item)


def _backend_protocol(backend: dict[str, Any]) -> str:
    return str(backend.get("protocol_type") or "vless_reality_singbox")


def _require_value(backend: dict[str, Any], key: str, label: str) -> Any:
    value = backend.get(key)
    if value is None or str(value).strip() == "":
        raise RemoteApplyError(f"backend {label} missing: {key}")
    return value


def _build_reality_backend_outbound(backend: dict[str, Any], outbound_tag: str) -> dict[str, Any]:
    return {
        "type": "vless",
        "tag": outbound_tag,
        "server": _require_value(backend, "ip", "Reality host"),
        "server_port": int(_require_value(backend, "public_port", "Reality public port")),
        "uuid": _require_value(backend, "generated_uuid", "Reality uuid"),
        "flow": "xtls-rprx-vision",
        "tls": {
            "enabled": True,
            "server_name": backend.get("selected_reality_target") or "www.example.com",
            "utls": {"enabled": True, "fingerprint": "chrome"},
            "reality": {
                "enabled": True,
                "public_key": _require_value(backend, "generated_public_key", "Reality public key"),
                "short_id": _require_value(backend, "generated_short_id", "Reality short id"),
            },
        },
    }


def _parse_vless_query(link: str) -> tuple[urllib.parse.ParseResult, dict[str, str]]:
    try:
        parsed = urllib.parse.urlparse(str(link or "").strip())
    except ValueError as exc:
        raise RemoteApplyError(f"imported VLESS link parse failed: {exc}") from exc
    if parsed.scheme != "vless" or not parsed.username or not parsed.hostname:
        raise RemoteApplyError("imported VLESS link is incomplete")
    query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
    return parsed, query


def _build_imported_vless_outbound(backend: dict[str, Any], outbound_tag: str) -> dict[str, Any]:
    parsed, query = _parse_vless_query(str(_require_value(backend, "last_vless_link", "imported VLESS link")))
    security = (query.get("security") or "").lower()
    transport_type = (query.get("type") or "tcp").lower()
    if security != "reality":
        raise RemoteApplyError("imported VLESS backend must be Reality; non-Reality imported nodes cannot be used as chain backend")
    if transport_type and transport_type != "tcp":
        raise RemoteApplyError("imported VLESS backend must use tcp transport for chain backend")
    public_key = query.get("pbk") or query.get("publicKey") or query.get("public_key")
    if not public_key:
        raise RemoteApplyError("imported VLESS backend missing Reality public key: pbk")
    server_name = query.get("sni") or query.get("serverName") or "www.example.com"
    outbound: dict[str, Any] = {
        "type": "vless",
        "tag": outbound_tag,
        "server": parsed.hostname,
        "server_port": int(parsed.port or backend.get("public_port") or 443),
        "uuid": urllib.parse.unquote(parsed.username),
        "tls": {
            "enabled": True,
            "server_name": server_name,
            "utls": {"enabled": True, "fingerprint": query.get("fp") or query.get("fingerprint") or "chrome"},
            "reality": {
                "enabled": True,
                "public_key": public_key,
            },
        },
    }
    flow = query.get("flow")
    if flow:
        outbound["flow"] = flow
    short_id = query.get("sid") or query.get("shortId") or query.get("short_id")
    if short_id:
        outbound["tls"]["reality"]["short_id"] = short_id
    return outbound


def _build_tunnel_backend_outbound(backend: dict[str, Any], outbound_tag: str) -> dict[str, Any]:
    cf_host = str(_require_value(backend, "cf_host", "tunnel host")).strip()
    ws_path = str(backend.get("ws_path") or "/").strip() or "/"
    return {
        "type": "vless",
        "tag": outbound_tag,
        "server": cf_host,
        "server_port": 443,
        "uuid": _require_value(backend, "generated_uuid", "tunnel uuid"),
        "tls": {
            "enabled": True,
            "server_name": cf_host,
            "utls": {"enabled": True, "fingerprint": "chrome"},
        },
        "transport": {
            "type": "ws",
            "path": ws_path,
            "headers": {"Host": cf_host},
        },
    }


def _build_backend_outbound(backend: dict[str, Any], outbound_tag: str) -> dict[str, Any]:
    protocol = _backend_protocol(backend)
    if protocol == "cf_vless_ws":
        raise RemoteApplyError("tunnel backend is disabled for chain proxy; use tunnel only as a single node")
    if protocol == "vless_reality_singbox":
        return _build_reality_backend_outbound(backend, outbound_tag)
    if protocol == "imported_vless":
        return _build_imported_vless_outbound(backend, outbound_tag)
    raise RemoteApplyError(f"unsupported chain backend protocol: {protocol}")


def build_front_chain_config(config: dict[str, Any], *, chain_tag: str, chain_uuid: str, backend: dict[str, Any]) -> dict[str, Any]:
    cfg = json.loads(json.dumps(config))
    inbound = _find_vless_inbound(cfg)
    users = inbound.setdefault("users", [])
    users = [u for u in users if u.get("name") != chain_tag and u.get("uuid") != chain_uuid]
    users.append({"name": chain_tag, "uuid": chain_uuid, "flow": "xtls-rprx-vision"})
    inbound["users"] = users

    outbound_tag = f"{chain_tag}-out"
    outbounds = cfg.setdefault("outbounds", [])
    _upsert_by_tag(outbounds, _build_backend_outbound(backend, outbound_tag))

    route = cfg.setdefault("route", {})
    rules = route.setdefault("rules", [])
    rules[:] = [r for r in rules if r.get("outbound") != outbound_tag and r.get("action") != outbound_tag]
    inbound_tag = inbound.get("tag")
    rule: dict[str, Any] = {"user": [chain_tag], "outbound": outbound_tag}
    if inbound_tag:
        rule["inbound"] = [inbound_tag]
    rules.insert(0, rule)
    route.setdefault("final", "direct")
    return cfg


def apply_front_chain_config(front: dict[str, Any], backend: dict[str, Any], *, chain_tag: str, chain_uuid: str) -> str:
    current = fetch_remote_singbox_config(front)
    updated = build_front_chain_config(current, chain_tag=chain_tag, chain_uuid=chain_uuid, backend=backend)
    with tempfile.TemporaryDirectory() as td:
        local = Path(td) / "config.json"
        local.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n")
        remote_tmp = f"/tmp/sing-box-chain-{chain_tag}.json"
        _scp_to(front, str(local), remote_tmp)

    backup = f"/etc/sing-box/config.json.bak.chain-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    script = " && ".join(
        [
            f"sing-box check -c {shlex.quote(remote_tmp)}",
            f"cp /etc/sing-box/config.json {shlex.quote(backup)}",
            f"mv {shlex.quote(remote_tmp)} /etc/sing-box/config.json",
            "systemctl restart sing-box || rc-service sing-box restart",
            "sleep 1",
            "sing-box check -c /etc/sing-box/config.json",
            "(systemctl is-active sing-box 2>/dev/null || rc-service sing-box status 2>/dev/null || true)",
        ]
    )
    out = _ssh(front, script, timeout=60)
    return f"backup={backup}\n{out}"
