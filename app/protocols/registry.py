from __future__ import annotations

from .models import ProtocolHandler

_PROTOCOLS: dict[str, ProtocolHandler] = {}


def register_protocol(handler: ProtocolHandler) -> ProtocolHandler:
    names = (handler.protocol_type, *handler.aliases)
    for name in names:
        key = str(name or "").strip()
        if not key:
            continue
        existing = _PROTOCOLS.get(key)
        if existing is not None and existing is not handler:
            raise ValueError(f"protocol already registered: {key}")
        _PROTOCOLS[key] = handler
    return handler


def get_protocol(protocol_type: object) -> ProtocolHandler | None:
    return _PROTOCOLS.get(str(protocol_type or "").strip())


def list_protocols() -> list[ProtocolHandler]:
    seen: set[int] = set()
    handlers: list[ProtocolHandler] = []
    for handler in _PROTOCOLS.values():
        marker = id(handler)
        if marker in seen:
            continue
        seen.add(marker)
        handlers.append(handler)
    return handlers
