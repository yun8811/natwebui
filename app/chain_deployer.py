import json
import os
import shlex
import subprocess
import tempfile
import time
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


def build_front_chain_config(config: dict[str, Any], *, chain_tag: str, chain_uuid: str, backend: dict[str, Any]) -> dict[str, Any]:
    cfg = json.loads(json.dumps(config))
    inbound = _find_vless_inbound(cfg)
    users = inbound.setdefault("users", [])
    users = [u for u in users if u.get("name") != chain_tag and u.get("uuid") != chain_uuid]
    users.append({"name": chain_tag, "uuid": chain_uuid, "flow": "xtls-rprx-vision"})
    inbound["users"] = users

    outbound_tag = f"{chain_tag}-out"
    outbounds = cfg.setdefault("outbounds", [])
    _upsert_by_tag(
        outbounds,
        {
            "type": "vless",
            "tag": outbound_tag,
            "server": backend["ip"],
            "server_port": int(backend["public_port"]),
            "uuid": backend["generated_uuid"],
            "flow": "xtls-rprx-vision",
            "network": "tcp",
            "tls": {
                "enabled": True,
                "server_name": backend["selected_reality_target"] or "www.microsoft.com",
                "utls": {"enabled": True, "fingerprint": "chrome"},
                "reality": {
                    "enabled": True,
                    "public_key": backend["generated_public_key"],
                    "short_id": backend["generated_short_id"],
                },
            },
        },
    )

    route = cfg.setdefault("route", {})
    rules = route.setdefault("rules", [])
    rules[:] = [r for r in rules if r.get("outbound") != outbound_tag and r.get("action") != outbound_tag]
    rules.insert(0, {"auth_user": [chain_tag], "outbound": outbound_tag})
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
