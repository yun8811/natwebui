from __future__ import annotations

import urllib.parse
from typing import Any

from .models import ProtocolBuildContext
from .registry import register_protocol


PROTOCOL_ANYTLS = "anytls"
ANYTLS_CERT_FILE = "/etc/sing-box/anytls-cert.pem"
ANYTLS_KEY_FILE = "/etc/sing-box/anytls-key.pem"
DEFAULT_ANYTLS_SERVER_NAME = "www.example.com"


def normalize_anytls_password(value: object) -> str:
    password = str(value or "").strip()
    return password


def anytls_server_name(node: dict[str, Any]) -> str:
    server_name = str(node.get("selected_reality_target") or "").strip().lower()
    return server_name or DEFAULT_ANYTLS_SERVER_NAME


class AnyTLSProtocol:
    protocol_type = PROTOCOL_ANYTLS
    aliases = ("anytls", "anytls_singbox")
    display_name = "AnyTLS"
    category = "direct"
    supports_deploy = True
    supports_subscription = True
    supports_chain_backend = False

    def build_inbound(self, context: ProtocolBuildContext) -> dict[str, Any]:
        node = context.node
        password = normalize_anytls_password(context.materials.get("generated_uuid"))
        return {
            "type": "anytls",
            "tag": f"anytls-in-{node['node_id']}",
            "listen": "::",
            "listen_port": int(node["listen_port"]),
            "users": [{"password": password}],
            "padding_scheme": [],
            "tls": {
                "enabled": True,
                "server_name": anytls_server_name(node),
                "certificate_path": ANYTLS_CERT_FILE,
                "key_path": ANYTLS_KEY_FILE,
            },
        }

    def build_share_link(self, context: ProtocolBuildContext) -> str:
        node = context.node
        password = normalize_anytls_password(context.materials.get("generated_uuid"))
        host = str(node.get("ip") or "").strip()
        port = int(node.get("public_port") or node.get("listen_port"))
        server_name = anytls_server_name(node)
        name = urllib.parse.quote(str(node.get("name") or "AnyTLS"), safe="")
        certificate_pin = str(context.materials.get("certificate_public_key_sha256") or "").strip()
        certificate_sha256 = str(context.materials.get("certificate_sha256") or "").strip()
        query = {
            "sni": server_name,
            "security": "tls",
            "type": "tcp",
            "fp": "chrome",
            "insecure": "1",
        }
        if certificate_pin:
            query["pinSHA256"] = certificate_pin
            query["pinnedPeerCertSha256"] = certificate_pin
        if certificate_sha256:
            query["hpkp"] = certificate_sha256
        encoded_query = urllib.parse.urlencode(query)
        return f"anytls://{urllib.parse.quote(password, safe='')}@{host}:{port}?{encoded_query}#{name}"


register_protocol(AnyTLSProtocol())
