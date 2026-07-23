from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProtocolBuildContext:
    node: dict[str, Any]
    materials: dict[str, Any]


class ProtocolHandler(Protocol):
    protocol_type: str
    aliases: tuple[str, ...]
    display_name: str
    category: str
    supports_deploy: bool
    supports_subscription: bool
    supports_chain_backend: bool

    def build_inbound(self, context: ProtocolBuildContext) -> dict[str, Any]: ...

    def build_share_link(self, context: ProtocolBuildContext) -> str: ...
