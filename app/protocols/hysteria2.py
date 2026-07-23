from __future__ import annotations

import base64
import binascii
import urllib.parse
from typing import Any

from .models import ProtocolBuildContext
from .registry import register_protocol


def _normalize_hex_sha256(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    compact = value.replace(":", "").lower()
    if len(compact) == 64 and all(ch in "0123456789abcdef" for ch in compact):
        return compact
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return value
    if len(decoded) == 32:
        return decoded.hex()
    return value


def _pin_sha256_for_uri(pin: str) -> str:
    return _normalize_hex_sha256(pin)


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


class Hysteria2Protocol:
    protocol_type = "hysteria2"
    aliases = ("hy2",)
    display_name = "Hysteria2"
    category = "direct"
    supports_deploy = True
    supports_subscription = True
    supports_chain_backend = False

    def build_inbound(self, context: ProtocolBuildContext) -> dict[str, Any]:
        node = context.node
        password = str(context.materials.get("generated_uuid") or "").strip()
        server_name = str(context.materials.get("selected_reality_target") or "www.example.com").strip() or "www.example.com"
        node_id = str(node.get("node_id") or "node")
        up_mbps = _positive_int(node.get("hy2_up_mbps"), 200)
        down_mbps = _positive_int(node.get("hy2_down_mbps"), 1000)
        return {
            "type": "hysteria2",
            "tag": f"hysteria2-{node_id}",
            "listen": "::",
            "listen_port": int(node["listen_port"]),
            "users": [{"password": password}],
            "up_mbps": up_mbps,
            "down_mbps": down_mbps,
            "ignore_client_bandwidth": False,
            "tls": {
                "enabled": True,
                "server_name": server_name,
                "alpn": ["h3"],
                "min_version": "1.3",
                "max_version": "1.3",
                "certificate_path": "/etc/sing-box/hysteria2-cert.pem",
                "key_path": "/etc/sing-box/hysteria2-key.pem",
            },
        }

    def build_share_link(self, context: ProtocolBuildContext) -> str:
        node = context.node
        password = urllib.parse.quote(str(context.materials.get("generated_uuid") or ""), safe="")
        host = str(node.get("ip") or "").strip()
        port = int(node.get("public_port") or node.get("listen_port") or 443)
        server_name = str(context.materials.get("selected_reality_target") or "www.example.com").strip() or "www.example.com"
        remark = urllib.parse.quote(str(context.materials.get("remark") or node.get("name") or "Hysteria2"), safe="")
        certificate_pin = str(context.materials.get("certificate_public_key_sha256") or "").strip()
        peer_cert_pin = str(context.materials.get("certificate_sha256") or certificate_pin).strip()
        up_mbps = _positive_int(node.get("hy2_up_mbps"), 200)
        down_mbps = _positive_int(node.get("hy2_down_mbps"), 1000)
        query_params = {
            "sni": server_name,
            "obfs": "none",
            "upmbps": str(up_mbps),
            "downmbps": str(down_mbps),
        }
        if certificate_pin:
            pin_hex = _pin_sha256_for_uri(certificate_pin)
            peer_cert_hex = _normalize_hex_sha256(peer_cert_pin)
            query_params["pinSHA256"] = pin_hex
            query_params["pinnedPeerCertSha256"] = peer_cert_hex or pin_hex
            query_params["verifyPeerCertByName"] = server_name
            query_params["insecure"] = "1"
        else:
            query_params["insecure"] = "1"
        query = urllib.parse.urlencode(query_params)
        return f"hysteria2://{password}@{host}:{port}?{query}#{remark}"


register_protocol(Hysteria2Protocol())
