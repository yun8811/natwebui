from __future__ import annotations

import ipaddress
import json
import shlex
import socket
import subprocess
import textwrap
import urllib.parse
import urllib.request
import uuid
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .config import AGENT_REPORT_PATH, APP_DIR, PUBLIC_BASE_URL
from .regions import replace_vless_fragment, vless_remark_for_node

REMOTE_APP_DIR = "/opt/natctl"
REMOTE_BIN_DIR = f"{REMOTE_APP_DIR}/bin"
REMOTE_AGENT_DIR = f"{REMOTE_APP_DIR}/agent"
REMOTE_STATE_DIR = f"{REMOTE_APP_DIR}/state"
REMOTE_LOG_DIR = f"{REMOTE_APP_DIR}/logs"
REMOTE_MARK_FILE = f"{REMOTE_STATE_DIR}/managed_by_natctl"
REMOTE_META_FILE = f"{REMOTE_STATE_DIR}/node_meta.json"
REMOTE_AGENT_SCRIPT = f"{REMOTE_AGENT_DIR}/report.sh"
REMOTE_SINGBOX_DIR = "/etc/sing-box"
REMOTE_SINGBOX_CONFIG = f"{REMOTE_SINGBOX_DIR}/config.json"
MARK_CONTENT = "managed_by=nat-webui-v1"
SINGBOX_RELEASE_API = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
PROTOCOL_TUNNEL = "cf_vless_ws"


class DeployError(Exception):
    def __init__(self, stage: str, message: str, raw_log: str):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.raw_log = raw_log


@dataclass
class DeployedNodeResult:
    node_id: str
    generated_vless_link: str
    generated_uuid: str
    generated_private_key: str
    generated_public_key: str
    generated_short_id: str
    selected_reality_target: str


@dataclass
class DeployResult:
    summary_log: str
    raw_log: str
    generated_vless_link: str
    generated_uuid: str
    generated_private_key: str
    generated_public_key: str
    generated_short_id: str
    selected_reality_target: str
    node_results: list[DeployedNodeResult] | None = None


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



def resolve_host_for_ssh(host: str) -> str:
    host = normalize_host_value(host)
    if not host:
        return host
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        info = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        for item in info:
            addr = item[4][0]
            if addr:
                return addr
    except socket.gaierror as exc:
        raise DeployError("ssh_probe", f"无法解析域名 {host}: {exc}", host) from exc
    raise DeployError("ssh_probe", f"无法解析域名 {host}", host)



class RemoteExecutor:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = resolve_host_for_ssh(host)
        self.original_host = host
        self.port = port
        self.user = user
        self.password = password

    def run(self, script: str, *, timeout: int = 120) -> str:
        proc = subprocess.run(
            [
                "sshpass",
                "-p",
                self.password,
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=12",
                "-p",
                str(self.port),
                f"{self.user}@{self.host}",
                "sh",
                "-s",
            ],
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, proc.args, output=output)
        return output.strip()



def shell_quote(value: str) -> str:
    return shlex.quote(value)



def choose_reality_target(node: dict | None = None) -> str:
    target = str((node or {}).get("selected_reality_target") or "").strip().lower()
    return target or "www.example.com"



def generate_reality_materials() -> tuple[str, str, str, str]:
    generated_uuid = str(uuid.uuid4())
    private_key_obj = X25519PrivateKey.generate()
    public_key_obj = private_key_obj.public_key()
    generated_private_key = urlsafe_b64encode(private_key_obj.private_bytes_raw()).decode().rstrip("=")
    generated_public_key = urlsafe_b64encode(public_key_obj.public_bytes_raw()).decode().rstrip("=")
    generated_short_id = uuid.uuid4().hex[:16]
    return generated_uuid, generated_private_key, generated_public_key, generated_short_id



def _fetch_latest_singbox() -> dict[str, Any]:
    req = urllib.request.Request(
        SINGBOX_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "nat-webui"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    assets = data.get("assets", []) or []
    chosen_by_arch: dict[str, dict[str, Any]] = {}
    for wanted_arch in ("amd64", "arm64", "armv7"):
        chosen = None
        for asset in assets:
            name = str(asset.get("name", ""))
            if "linux" in name and wanted_arch in name and name.endswith(".tar.gz"):
                if "musl" in name:
                    chosen = asset
                    break
                chosen = chosen or asset
        if chosen:
            chosen_by_arch[wanted_arch] = {
                "name": str(chosen.get("name", "")).strip(),
                "url": str(chosen.get("browser_download_url", "")).strip(),
            }
    if "amd64" not in chosen_by_arch:
        raise DeployError("download", "无法找到适合的 sing-box Linux amd64 发行包", json.dumps(data, ensure_ascii=False, indent=2)[:8000])
    return {"tag": str(data.get("tag_name", "")).strip(), "assets": chosen_by_arch, **chosen_by_arch["amd64"]}



def build_singbox_config(node: dict, *, generated_uuid: str, generated_private_key: str, generated_short_id: str, selected_reality_target: str) -> str:
    return build_multi_singbox_config([
        {
            "node": node,
            "generated_uuid": generated_uuid,
            "generated_private_key": generated_private_key,
            "generated_short_id": generated_short_id,
            "selected_reality_target": selected_reality_target,
        }
    ])


def build_multi_singbox_config(entries: list[dict[str, Any]]) -> str:
    inbounds = []
    for entry in entries:
        node = entry["node"]
        selected_reality_target = entry["selected_reality_target"]
        node_id = str(node.get("node_id") or "node")
        inbounds.append(
            {
                "type": "vless",
                "tag": f"vless-reality-{node_id}",
                "listen": "::",
                "listen_port": int(node["listen_port"]),
                "users": [{"uuid": entry["generated_uuid"], "flow": "xtls-rprx-vision"}],
                "tls": {
                    "enabled": True,
                    "server_name": selected_reality_target,
                    "reality": {
                        "enabled": True,
                        "handshake": {
                            "server": selected_reality_target,
                            "server_port": 443,
                        },
                        "private_key": entry["generated_private_key"],
                        "short_id": [entry["generated_short_id"]],
                    },
                },
            }
        )
    config = {"log": {"level": "info"}, "inbounds": inbounds, "outbounds": [{"type": "direct", "tag": "direct"}]}
    return json.dumps(config, ensure_ascii=False, indent=2)



def build_tunnel_singbox_config(node: dict, *, generated_uuid: str) -> str:
    ws_path = str(node.get("ws_path") or "/").strip() or "/"
    if not ws_path.startswith("/"):
        ws_path = f"/{ws_path}"
    config = {
        "log": {"level": "info"},
        "inbounds": [
            {
                "type": "vless",
                "tag": "vless-ws-in",
                "listen": "127.0.0.1",
                "listen_port": int(node.get("ws_port") or node.get("listen_port") or 8080),
                "users": [{"uuid": generated_uuid}],
                "transport": {"type": "ws", "path": ws_path},
            }
        ],
        "outbounds": [{"type": "direct", "tag": "direct"}],
    }
    return json.dumps(config, ensure_ascii=False, indent=2)



def build_tunnel_node_meta(node: dict, *, generated_uuid: str) -> str:
    payload = {
        "node_id": node["node_id"],
        "protocol_type": node["protocol_type"],
        "public_port": node.get("public_port") or 443,
        "listen_port": node.get("listen_port") or node.get("ws_port") or 8080,
        "ws_port": node.get("ws_port") or 8080,
        "ws_path": node.get("ws_path") or "/",
        "cf_host": node.get("cf_host"),
        "generated_uuid": generated_uuid,
        "generated_public_key": "",
        "generated_short_id": "",
        "selected_reality_target": str(node.get("cf_host") or ""),
        "agent_token": node["agent_token"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)



def build_tunnel_vless_link(node: dict, *, generated_uuid: str) -> str:
    cf_host = str(node.get("cf_host") or "").strip().replace("https://", "").replace("http://", "").strip("/")
    ws_path = str(node.get("ws_path") or "/").strip() or "/"
    if not ws_path.startswith("/"):
        ws_path = f"/{ws_path}"
    name = urllib.parse.quote(vless_remark_for_node(node, "tunnel"), safe="")
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
    return f"vless://{generated_uuid}@{cf_host}:443?{query}#{name}"







def build_node_meta(node: dict, *, generated_uuid: str, generated_public_key: str, generated_short_id: str, selected_reality_target: str) -> str:
    return build_multi_node_meta([
        {
            "node": node,
            "generated_uuid": generated_uuid,
            "generated_public_key": generated_public_key,
            "generated_short_id": generated_short_id,
            "selected_reality_target": selected_reality_target,
        }
    ])


def build_multi_node_meta(entries: list[dict[str, Any]]) -> str:
    nodes = []
    for entry in entries:
        node = entry["node"]
        nodes.append(
            {
                "node_id": node["node_id"],
                "protocol_type": node["protocol_type"],
                "public_port": node["public_port"],
                "listen_port": node["listen_port"],
                "selected_reality_target": entry["selected_reality_target"],
                "generated_uuid": entry["generated_uuid"],
                "generated_public_key": entry["generated_public_key"],
                "generated_short_id": entry["generated_short_id"],
                "agent_token": node["agent_token"],
            }
        )
    payload = nodes[0].copy()
    payload["nodes"] = nodes
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_agent_script(node: dict) -> str:
    if not PUBLIC_BASE_URL:
        raise DeployError("prepare", "缺少 NAT_WEBUI_PUBLIC_BASE_URL，无法生成 Agent 上报地址", "NAT_WEBUI_PUBLIC_BASE_URL is required")
    report_url = f"{PUBLIC_BASE_URL}{AGENT_REPORT_PATH}"
    public_ip = json.dumps(node["ip"], ensure_ascii=False)
    script = """#!/bin/sh
set -eu
meta_file={meta_file}
if [ ! -f "$meta_file" ]; then
  echo "missing meta file" >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  apk add --no-cache curl >/dev/null
fi
hostname_val=$(hostname 2>/dev/null || echo unknown)
report_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
python3 - <<'PYEOF' > /tmp/natctl-agent-reports.jsonl
import json
from pathlib import Path
meta = json.loads(Path({meta_file_py}).read_text())
nodes = meta.get("nodes") or [meta]
report_time = "__REPORT_TIME__"
hostname = "__HOSTNAME__"
public_ip = {public_ip}
for item in nodes:
    payload = {{
        "node_id": item["node_id"],
        "agent_token": item["agent_token"],
        "overall_status": "online",
        "report_time": report_time,
        "hostname": hostname,
        "public_ip": public_ip,
        "public_port": item.get("public_port"),
        "listen_port": item.get("listen_port"),
        "protocol_type": item.get("protocol_type"),
        "generated_uuid": item.get("generated_uuid"),
        "generated_public_key": item.get("generated_public_key"),
        "generated_short_id": item.get("generated_short_id"),
        "selected_reality_target": item.get("selected_reality_target"),
    }}
    print(json.dumps(payload, ensure_ascii=False))
PYEOF
sed -i "s/__REPORT_TIME__/$report_time/g; s/__HOSTNAME__/$hostname_val/g" /tmp/natctl-agent-reports.jsonl
while IFS= read -r payload; do
  [ -n "$payload" ] || continue
  printf '%s' "$payload" | curl -fsS -H 'Content-Type: application/json' --data-binary @- {report_url} >/dev/null
done < /tmp/natctl-agent-reports.jsonl
"""
    return script.format(
        meta_file=shell_quote(REMOTE_META_FILE),
        meta_file_py=repr(REMOTE_META_FILE),
        public_ip=public_ip,
        report_url=shell_quote(report_url),
    )


def build_remote_script(node: dict, *, singbox_config: str, node_meta: str, agent_script: str, singbox_archive_url: str, singbox_archive_name: str) -> str:
    cron_block = "* * * * * /opt/natctl/agent/report.sh >> /opt/natctl/logs/agent.log 2>&1"
    openrc_script = textwrap.dedent(
        """\
        #!/sbin/openrc-run
        description="sing-box NAT WebUI service"
        command="/usr/local/bin/sing-box"
        command_args="run -c /etc/sing-box/config.json"
        command_background="yes"
        pidfile="/run/sing-box.pid"
        depend() {
          need net
        }
        """
    )
    systemd_script = textwrap.dedent(
        """\
        [Unit]
        Description=sing-box NAT WebUI service
        After=network-online.target
        Wants=network-online.target

        [Service]
        ExecStart=/usr/local/bin/sing-box run -c /etc/sing-box/config.json
        Restart=on-failure
        RestartSec=3
        LimitNOFILE=1048576

        [Install]
        WantedBy=multi-user.target
        """
    )
    return textwrap.dedent(
        f"""\
        set -eu
        mkdir -p {shell_quote(REMOTE_BIN_DIR)} {shell_quote(REMOTE_AGENT_DIR)} {shell_quote(REMOTE_STATE_DIR)} {shell_quote(REMOTE_LOG_DIR)} {shell_quote(REMOTE_SINGBOX_DIR)} /tmp/natctl-singbox /etc/systemd/system
        if command -v apk >/dev/null 2>&1; then
          apk add --no-cache curl ca-certificates tar gzip python3 coreutils iproute2 >/dev/null
        elif command -v apt-get >/dev/null 2>&1; then
          export DEBIAN_FRONTEND=noninteractive
          apt-get update -y >/dev/null
          apt-get install -y curl ca-certificates tar gzip python3 coreutils iproute2 cron >/dev/null
        else
          echo 'ERROR: unsupported package manager'
          exit 1
        fi
        if ! command -v python3 >/dev/null 2>&1; then
          echo 'ERROR: python3 install failed or unavailable'
          exit 1
        fi
        if ! command -v sing-box >/dev/null 2>&1; then
          echo 'INFO: sing-box missing, downloading release package'
          rm -rf /tmp/natctl-singbox/*
          curl -fsSL {shell_quote(singbox_archive_url)} -o /tmp/natctl-singbox/{shell_quote(singbox_archive_name)}
          tar -xzf /tmp/natctl-singbox/{shell_quote(singbox_archive_name)} -C /tmp/natctl-singbox
          bin_path=$(find /tmp/natctl-singbox -type f -name sing-box | head -n 1)
          if [ -z "$bin_path" ]; then
            echo 'ERROR: sing-box binary not found in archive'
            exit 1
          fi
          install -m 0755 "$bin_path" /usr/local/bin/sing-box
        fi
        python3 - <<'PYEOF'
from pathlib import Path
Path({REMOTE_MARK_FILE!r}).write_text({(MARK_CONTENT + chr(10))!r})
Path({REMOTE_SINGBOX_CONFIG!r}).write_text({(singbox_config + chr(10))!r})
Path({REMOTE_META_FILE!r}).write_text({(node_meta + chr(10))!r})
Path({REMOTE_AGENT_SCRIPT!r}).write_text({agent_script!r})
Path('/etc/init.d/sing-box').write_text({openrc_script!r})
Path('/etc/systemd/system/sing-box.service').write_text({systemd_script!r})
PYEOF
        chmod +x {shell_quote(REMOTE_AGENT_SCRIPT)} /etc/init.d/sing-box
        if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
          systemctl stop sing-box >/dev/null 2>&1 || true
        fi
        if command -v rc-service >/dev/null 2>&1; then
          rc-service sing-box stop >/dev/null 2>&1 || true
        fi
        sleep 1
        if command -v ss >/dev/null 2>&1; then
          port_pids=$(ss -ltnp 2>/dev/null | awk '$4 ~ /:{int(node["listen_port"])}$/ {{print $0}}' | sed -En 's/.*pid=([0-9][0-9]*).*/\\1/p' | sort -u)
          for pid in $port_pids; do
            cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
            case "$cmdline" in
              *'/usr/local/bin/sing-box run -c /etc/sing-box/config.json'*|*'sing-box run -c /etc/sing-box/config.json'*)
                echo "INFO: stopping stale NAT WebUI sing-box process $pid on port {int(node["listen_port"])}"
                kill "$pid" 2>/dev/null || true
                ;;
              *)
                echo "ERROR: port {int(node["listen_port"])} is occupied by non-NAT-WebUI process: $pid $cmdline"
                ss -ltnp 2>/dev/null | awk '$4 ~ /:{int(node["listen_port"])}$/ {{print $0}}' || true
                exit 1
                ;;
            esac
          done
          sleep 1
          if ss -ltnp 2>/dev/null | awk '$4 ~ /:{int(node["listen_port"])}$/ {{print $0}}' | grep -q .; then
            echo 'ERROR: sing-box listen port is still occupied after cleanup'
            ss -ltnp 2>/dev/null | awk '$4 ~ /:{int(node["listen_port"])}$/ {{print $0}}' || true
            exit 1
          fi
        else
          pkill -f 'sing-box run -c /etc/sing-box/config.json' 2>/dev/null || true
          sleep 1
        fi
        if ! /usr/local/bin/sing-box check -c /etc/sing-box/config.json >/opt/natctl/logs/sing-box-check.log 2>&1; then
          echo 'ERROR: sing-box config check failed'
          cat /opt/natctl/logs/sing-box-check.log
          exit 1
        fi
        if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
          systemctl daemon-reload >/dev/null 2>&1 || true
          systemctl enable sing-box >/dev/null 2>&1 || true
          systemctl restart sing-box >/dev/null 2>&1
          if command -v crontab >/dev/null 2>&1; then
            systemctl enable --now cron >/dev/null 2>&1 || systemctl enable --now crond >/dev/null 2>&1 || true
          fi
          sleep 1
          if ! systemctl is-active --quiet sing-box; then
            echo 'ERROR: sing-box systemd service is not active'
            systemctl status sing-box --no-pager 2>/dev/null || true
            journalctl -u sing-box -n 80 --no-pager 2>/dev/null || true
            exit 1
          fi
        elif command -v rc-service >/dev/null 2>&1; then
          rc-update add sing-box default >/dev/null 2>&1 || true
          rc-service sing-box restart >/dev/null 2>&1 || rc-service sing-box start >/dev/null 2>&1
          sleep 1
          if ! rc-service sing-box status >/dev/null 2>&1; then
            echo 'ERROR: sing-box OpenRC service is not running'
            tail -80 /opt/natctl/logs/sing-box.log 2>/dev/null || true
            exit 1
          fi
        else
          pkill -f 'sing-box run -c /etc/sing-box/config.json' 2>/dev/null || true
          nohup /usr/local/bin/sing-box run -c /etc/sing-box/config.json >/opt/natctl/logs/sing-box.log 2>&1 &
          sleep 1
          if ! pgrep -f 'sing-box run -c /etc/sing-box/config.json' >/dev/null 2>&1; then
            echo 'ERROR: sing-box process exited after start'
            tail -80 /opt/natctl/logs/sing-box.log 2>/dev/null || true
            exit 1
          fi
        fi
        if command -v ss >/dev/null 2>&1; then
          if ! ss -ltn | awk '{{print $4}}' | grep -Eq '(^|:){int(node["listen_port"])}$'; then
            echo 'ERROR: sing-box is not listening on port {int(node["listen_port"])}'
            ss -ltnp 2>/dev/null || ss -ltn 2>/dev/null || true
            exit 1
          fi
        fi
        if command -v crontab >/dev/null 2>&1; then
          (crontab -l 2>/dev/null | grep -v 'NAT-WEBUI-AGENT' | grep -v '/opt/natctl/agent/report.sh'; \
            echo '# BEGIN NAT-WEBUI-AGENT'; \
            echo {shell_quote(cron_block)}; \
            echo '# END NAT-WEBUI-AGENT') | crontab -
        else
          echo 'WARN: crontab unavailable, run one-shot agent report only'
        fi
        {shell_quote(REMOTE_AGENT_SCRIPT)} >/opt/natctl/logs/agent-once.log 2>&1 || true
        echo 'OK: deploy finished'
        """
    )


def build_tunnel_remote_script(
    node: dict,
    *,
    singbox_config: str,
    node_meta: str,
    agent_script: str,
    singbox_assets: dict[str, dict[str, str]],
) -> str:
    cron_block = "* * * * * /opt/natctl/agent/report.sh >> /opt/natctl/logs/agent.log 2>&1"
    cf_token = str(node.get("cf_tunnel_token") or "").strip()
    listen_port = int(node.get("ws_port") or node.get("listen_port") or 8080)
    amd64_url = singbox_assets.get("amd64", {}).get("url", "")
    arm64_url = singbox_assets.get("arm64", {}).get("url", amd64_url)
    armv7_url = singbox_assets.get("armv7", {}).get("url", amd64_url)
    openrc_singbox = textwrap.dedent("""\
        #!/sbin/openrc-run
        name="sing-box"
        command="/usr/local/bin/sing-box"
        command_args="run -c /etc/sing-box/config.json"
        command_background="yes"
        pidfile="/run/sing-box.pid"
        depend() { need net; }
        """)
    openrc_cloudflared = textwrap.dedent("""\
        #!/sbin/openrc-run
        name="cloudflared-tunnel"
        command="/usr/local/bin/cloudflared"
        command_args="tunnel run --token-file /etc/cloudflared/token"
        command_background="yes"
        pidfile="/run/cloudflared-tunnel.pid"
        depend() { need net; }
        """)
    systemd_singbox = textwrap.dedent("""\
        [Unit]
        Description=sing-box tunnel service
        After=network-online.target
        Wants=network-online.target

        [Service]
        ExecStart=/usr/local/bin/sing-box run -c /etc/sing-box/config.json
        Restart=on-failure
        RestartSec=3
        LimitNOFILE=1048576

        [Install]
        WantedBy=multi-user.target
        """)
    systemd_cloudflared = textwrap.dedent("""\
        [Unit]
        Description=Cloudflare Tunnel
        After=network-online.target
        Wants=network-online.target

        [Service]
        ExecStart=/usr/local/bin/cloudflared tunnel run --token-file /etc/cloudflared/token
        Restart=on-failure
        RestartSec=5

        [Install]
        WantedBy=multi-user.target
        """)
    return textwrap.dedent(
        f"""\
        set -eu
        mkdir -p {shell_quote(REMOTE_BIN_DIR)} {shell_quote(REMOTE_AGENT_DIR)} {shell_quote(REMOTE_STATE_DIR)} {shell_quote(REMOTE_LOG_DIR)} {shell_quote(REMOTE_SINGBOX_DIR)} /etc/cloudflared /tmp/natctl-singbox
        if command -v apk >/dev/null 2>&1; then
          apk add --no-cache curl ca-certificates tar gzip python3 coreutils >/dev/null
        elif command -v apt-get >/dev/null 2>&1; then
          export DEBIAN_FRONTEND=noninteractive
          apt-get update -y >/dev/null
          apt-get install -y curl ca-certificates tar gzip python3 coreutils >/dev/null
        else
          echo 'ERROR: unsupported package manager'
          exit 1
        fi
        if ! command -v python3 >/dev/null 2>&1; then
          echo 'ERROR: python3 install failed or unavailable'
          exit 1
        fi
        arch=$(uname -m)
        case "$arch" in
          x86_64|amd64) sb_url={shell_quote(amd64_url)}; cf_arch=amd64 ;;
          aarch64|arm64) sb_url={shell_quote(arm64_url)}; cf_arch=arm64 ;;
          armv7l|armv7*) sb_url={shell_quote(armv7_url)}; cf_arch=arm ;;
          *) echo "ERROR: unsupported arch $arch"; exit 1 ;;
        esac
        if ! command -v sing-box >/dev/null 2>&1; then
          echo 'INFO: sing-box missing, downloading release package'
          curl -fL "$sb_url" -o /tmp/natctl-singbox/sing-box.tar.gz
          tar -xzf /tmp/natctl-singbox/sing-box.tar.gz -C /tmp/natctl-singbox
          bin_path=$(find /tmp/natctl-singbox -type f -name sing-box | head -n 1)
          if [ -z "$bin_path" ]; then
            echo 'ERROR: sing-box binary not found in archive'
            exit 1
          fi
          install -m 0755 "$bin_path" /usr/local/bin/sing-box
        fi
        if ! command -v cloudflared >/dev/null 2>&1; then
          curl -fL -o /usr/local/bin/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$cf_arch"
          chmod +x /usr/local/bin/cloudflared
        fi
        python3 - <<'PYEOF'
from pathlib import Path
Path({REMOTE_MARK_FILE!r}).write_text({(MARK_CONTENT + chr(10))!r})
Path({REMOTE_SINGBOX_CONFIG!r}).write_text({(singbox_config + chr(10))!r})
Path({REMOTE_META_FILE!r}).write_text({(node_meta + chr(10))!r})
Path({REMOTE_AGENT_SCRIPT!r}).write_text({agent_script!r})
Path('/etc/cloudflared/token').write_text({(cf_token + chr(10))!r})
Path('/etc/init.d/sing-box').write_text({openrc_singbox!r})
Path('/etc/init.d/cloudflared-tunnel').write_text({openrc_cloudflared!r})
Path('/etc/systemd/system/sing-box.service').write_text({systemd_singbox!r})
Path('/etc/systemd/system/cloudflared-tunnel.service').write_text({systemd_cloudflared!r})
PYEOF
        chmod 600 /etc/cloudflared/token
        chmod +x {shell_quote(REMOTE_AGENT_SCRIPT)} /etc/init.d/sing-box /etc/init.d/cloudflared-tunnel 2>/dev/null || true
        if command -v systemctl >/dev/null 2>&1; then
          systemctl daemon-reload
          systemctl enable --now sing-box.service >/dev/null 2>&1 || true
          systemctl enable --now cloudflared-tunnel.service >/dev/null 2>&1 || true
          systemctl restart sing-box.service cloudflared-tunnel.service
          sleep 2
          systemctl is-active --quiet sing-box.service
          systemctl is-active --quiet cloudflared-tunnel.service
        elif command -v rc-service >/dev/null 2>&1; then
          rc-update add sing-box default >/dev/null 2>&1 || true
          rc-update add cloudflared-tunnel default >/dev/null 2>&1 || true
          rc-service sing-box restart >/dev/null 2>&1 || rc-service sing-box start >/dev/null 2>&1
          rc-service cloudflared-tunnel restart >/dev/null 2>&1 || rc-service cloudflared-tunnel start >/dev/null 2>&1
        else
          /usr/local/bin/sing-box run -c /etc/sing-box/config.json >{shell_quote(REMOTE_LOG_DIR)}/sing-box.log 2>&1 &
          /usr/local/bin/cloudflared tunnel run --token-file /etc/cloudflared/token >{shell_quote(REMOTE_LOG_DIR)}/cloudflared.log 2>&1 &
        fi
        (crontab -l 2>/dev/null | grep -v 'NAT-WEBUI-AGENT' | grep -v '/opt/natctl/agent/report.sh'; \
          echo '# BEGIN NAT-WEBUI-AGENT'; \
          echo {shell_quote(cron_block)}; \
          echo '# END NAT-WEBUI-AGENT') | crontab - 2>/dev/null || true
        if command -v ss >/dev/null 2>&1; then
          ss -ltn | grep -q ":{listen_port} "
        elif command -v netstat >/dev/null 2>&1; then
          netstat -ltn | grep -q ":{listen_port} "
        fi
        echo 'OK: tunnel deploy finished'
        """
    )




def build_vless_link(node: dict, *, generated_uuid: str, generated_public_key: str, generated_short_id: str, selected_reality_target: str) -> str:
    public_host = normalize_host_value(str(node.get("ip") or ""))
    if not public_host:
        public_host = str(node.get("ip") or "").strip()
    return replace_vless_fragment(
        (
            f"vless://{generated_uuid}@{public_host}:{node['public_port']}"
            f"?security=reality&sni={selected_reality_target}&pbk={generated_public_key}"
            f"&sid={generated_short_id}&type=tcp&flow=xtls-rprx-vision"
        ),
        vless_remark_for_node(node, allow_lookup=True),
    )



def run_multi_real_deploy(nodes: list[dict]) -> DeployResult:
    if not nodes:
        raise DeployError("prepare", "没有可部署节点", "empty node list")
    primary_node = nodes[0]
    entries = []
    for item in nodes:
        generated_uuid, generated_private_key, generated_public_key, generated_short_id = generate_reality_materials()
        selected_reality_target = choose_reality_target(item)
        entries.append(
            {
                "node": item,
                "generated_uuid": generated_uuid,
                "generated_private_key": generated_private_key,
                "generated_public_key": generated_public_key,
                "generated_short_id": generated_short_id,
                "selected_reality_target": selected_reality_target,
            }
        )
    singbox_config = build_multi_singbox_config(entries)
    node_meta = build_multi_node_meta(entries)
    agent_script = build_agent_script(primary_node)
    singbox_release = _fetch_latest_singbox()
    logs: list[str] = []

    def add(stage: str, output: str) -> None:
        logs.append(f"[stage] {stage}\n{output}".rstrip())

    executor = RemoteExecutor(
        host=str(primary_node["ip"]),
        port=int(primary_node["ssh_port"]),
        user=str(primary_node["ssh_user"]),
        password=str(primary_node["ssh_password"]),
    )
    try:
        add("ssh_probe", executor.run("echo CONNECTED", timeout=25))
    except Exception as exc:
        raw = "\n".join(logs + [f"SSH probe failed: {exc}"])
        raise DeployError("ssh_probe", "SSH 连接失败", raw)
    try:
        add("system_probe", executor.run("uname -a; cat /etc/alpine-release 2>/dev/null || cat /etc/os-release", timeout=30))
    except Exception as exc:
        raw = "\n".join(logs + [f"System probe failed: {exc}"])
        raise DeployError("system_probe", "系统探测失败", raw)
    try:
        remote_script = build_remote_script(
            primary_node,
            singbox_config=singbox_config,
            node_meta=node_meta,
            agent_script=agent_script,
            singbox_archive_url=singbox_release["url"],
            singbox_archive_name=singbox_release["name"],
        )
        add("deploy", executor.run(remote_script, timeout=420))
    except Exception as exc:
        raw = "\n".join(logs + [f"Deploy failed: {exc}"])
        raise DeployError("deploy", "远端部署失败", raw)

    node_results = []
    for entry in entries:
        node = entry["node"]
        generated_vless_link = build_vless_link(
            node,
            generated_uuid=entry["generated_uuid"],
            generated_public_key=entry["generated_public_key"],
            generated_short_id=entry["generated_short_id"],
            selected_reality_target=entry["selected_reality_target"],
        )
        node_results.append(
            DeployedNodeResult(
                node_id=node["node_id"],
                generated_vless_link=generated_vless_link,
                generated_uuid=entry["generated_uuid"],
                generated_private_key=entry["generated_private_key"],
                generated_public_key=entry["generated_public_key"],
                generated_short_id=entry["generated_short_id"],
                selected_reality_target=entry["selected_reality_target"],
            )
        )
    primary_result = next((item for item in node_results if item.node_id == primary_node["node_id"]), node_results[0])
    ports = ", ".join(str(entry["node"]["listen_port"]) for entry in entries)
    summary = textwrap.dedent(
        f"""\
        真实部署已完成
        目标节点：{primary_node['ip']}:{primary_node['ssh_port']}
        同 VPS 节点数：{len(entries)}
        监听端口：{ports}
        sing-box：{singbox_release['name']}
        """
    ).strip()
    return DeployResult(
        summary_log=summary,
        raw_log="\n".join(logs),
        generated_vless_link=primary_result.generated_vless_link,
        generated_uuid=primary_result.generated_uuid,
        generated_private_key=primary_result.generated_private_key,
        generated_public_key=primary_result.generated_public_key,
        generated_short_id=primary_result.generated_short_id,
        selected_reality_target=primary_result.selected_reality_target,
        node_results=node_results,
    )


def run_real_deploy(node: dict) -> DeployResult:
    logs: list[str] = []

    def add(stage: str, content: str) -> None:
        content = (content or "").strip()
        logs.append(f"[stage] {stage}")
        if content:
            logs.append(content)

    executor = RemoteExecutor(
        host=str(node["ip"]),
        port=int(node["ssh_port"]),
        user=str(node["ssh_user"]),
        password=str(node["ssh_password"]),
    )

    protocol_type = str(node.get("protocol_type") or "vless")
    generated_uuid, generated_private_key, generated_public_key, generated_short_id = generate_reality_materials()
    selected_reality_target = choose_reality_target(node)

    if protocol_type == "cf_vless_ws":
        singbox_config = build_tunnel_singbox_config(node, generated_uuid=generated_uuid)
        node_meta = build_tunnel_node_meta(node, generated_uuid=generated_uuid)
    else:
        singbox_config = build_singbox_config(
            node,
            generated_uuid=generated_uuid,
            generated_private_key=generated_private_key,
            generated_short_id=generated_short_id,
            selected_reality_target=selected_reality_target,
        )
        node_meta = build_node_meta(
            node,
            generated_uuid=generated_uuid,
            generated_public_key=generated_public_key,
            generated_short_id=generated_short_id,
            selected_reality_target=selected_reality_target,
        )
    agent_script = build_agent_script(node)
    singbox_release = _fetch_latest_singbox()

    try:
        add("ssh_probe", executor.run("echo CONNECTED", timeout=25))
    except Exception as exc:
        raw = "\n".join(logs + [f"SSH probe failed: {exc}"])
        raise DeployError("ssh_probe", "SSH 连接失败", raw)

    try:
        add("system_probe", executor.run("uname -a; cat /etc/alpine-release 2>/dev/null || cat /etc/os-release", timeout=30))
    except Exception as exc:
        raw = "\n".join(logs + [f"System probe failed: {exc}"])
        raise DeployError("system_probe", "系统探测失败", raw)

    try:
        if protocol_type == "cf_vless_ws":
            remote_script = build_tunnel_remote_script(
                node,
                singbox_config=singbox_config,
                node_meta=node_meta,
                agent_script=agent_script,
                singbox_assets=singbox_release.get("assets", {}),
            )
        else:
            remote_script = build_remote_script(
                node,
                singbox_config=singbox_config,
                node_meta=node_meta,
                agent_script=agent_script,
                singbox_archive_url=singbox_release["url"],
                singbox_archive_name=singbox_release["name"],
            )
        add("deploy", executor.run(remote_script, timeout=420))
    except Exception as exc:
        raw = "\n".join(logs + [f"Deploy failed: {exc}"])
        raise DeployError("deploy", "远端部署失败", raw)

    if protocol_type == "cf_vless_ws":
        generated_vless_link = build_tunnel_vless_link(node, generated_uuid=generated_uuid)
        summary = textwrap.dedent(
            f"""\
            Tunnel 部署已完成
            目标节点：{node['ip']}:{node['ssh_port']}
            应用路由：{node.get('cf_host')}
            本地 WS 端口：{node.get('ws_port') or 8080}
            WS 路径：{node.get('ws_path') or '/'}
            sing-box：{singbox_release['tag']}
            cloudflared：latest
            """
        ).strip()
    else:
        generated_vless_link = build_vless_link(
            node,
            generated_uuid=generated_uuid,
            generated_public_key=generated_public_key,
            generated_short_id=generated_short_id,
            selected_reality_target=selected_reality_target,
        )
        summary = textwrap.dedent(
            f"""\
            真实部署已完成
            目标节点：{node['ip']}:{node['ssh_port']}
            监听端口：{node['listen_port']}
            公网端口：{node['public_port']}
            Reality 目标：{selected_reality_target}
            sing-box：{singbox_release['name']}
            """
        ).strip()
    return DeployResult(
        summary_log=summary,
        raw_log="\n".join(logs),
        generated_vless_link=generated_vless_link,
        generated_uuid=generated_uuid,
        generated_private_key=generated_private_key,
        generated_public_key=generated_public_key,
        generated_short_id=generated_short_id,
        selected_reality_target=selected_reality_target,
    )
