from __future__ import annotations

from typing import Any

from .models import ProtocolBuildContext
from .registry import register_protocol


class VlessRealityProtocol:
    protocol_type = "vless_reality_singbox"
    aliases = ("vless_reality", "")
    display_name = "VLESS Reality"
    category = "direct"
    supports_deploy = True
    supports_subscription = True
    supports_chain_backend = True

    def build_inbound(self, context: ProtocolBuildContext) -> dict[str, Any]:
        node = context.node
        materials = context.materials
        selected_reality_target = str(materials["selected_reality_target"])
        node_id = str(node.get("node_id") or "node")
        return {
            "type": "vless",
            "tag": f"vless-reality-{node_id}",
            "listen": "::",
            "listen_port": int(node["listen_port"]),
            "users": [{"uuid": materials["generated_uuid"], "flow": "xtls-rprx-vision"}],
            "tls": {
                "enabled": True,
                "server_name": selected_reality_target,
                "reality": {
                    "enabled": True,
                    "handshake": {
                        "server": selected_reality_target,
                        "server_port": 443,
                    },
                    "private_key": materials["generated_private_key"],
                    "short_id": [materials["generated_short_id"]],
                },
            },
        }

    def build_share_link(self, context: ProtocolBuildContext) -> str:
        from app.regions import vless_remark_for_node

        node = context.node
        materials = context.materials
        remark = str(materials.get("remark") or vless_remark_for_node(node, allow_lookup=True))
        query = (
            f"encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni={materials['selected_reality_target']}"
            f"&fp=chrome&pbk={materials['generated_public_key']}"
            f"&sid={materials['generated_short_id']}&type=tcp&headerType=none"
        )
        return f"vless://{materials['generated_uuid']}@{node['ip']}:{node['public_port']}?{query}#{remark}"


register_protocol(VlessRealityProtocol())
