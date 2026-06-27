from __future__ import annotations

import json
import socket
import urllib.parse
import urllib.request
from typing import Any

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

COUNTRY_NAME_TO_CODE = {
    "香港": "HK",
    "日本": "JP",
    "韩国": "KR",
    "美国": "US",
    "台湾": "TW",
    "新加坡": "SG",
    "土耳其": "TR",
    "澳洲": "AU",
    "澳大利亚": "AU",
    "中国": "CN",
    "马来西亚": "MY",
    "德国": "DE",
    "英国": "GB",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "japan": "JP",
    "korea": "KR",
    "south korea": "KR",
    "hong kong": "HK",
    "taiwan": "TW",
    "singapore": "SG",
    "turkey": "TR",
    "australia": "AU",
    "china": "CN",
    "malaysia": "MY",
    "germany": "DE",
    "united kingdom": "GB",
    "uk": "GB",
}

_IP_REGION_CACHE: dict[str, dict[str, Any]] = {}


def _node_value(node: dict | object | None, key: str) -> str:
    if node is None:
        return ""
    try:
        value = node[key]  # type: ignore[index]
    except Exception:
        value = getattr(node, key, "")
    return str(value or "").strip()


def normalize_host_value(value: str) -> str:
    host = str(value or "").strip()
    if not host:
        return ""
    if "://" in host:
        parsed = urllib.parse.urlparse(host)
        host = parsed.hostname or ""
    else:
        host = host.split("/", 1)[0].strip()
        if host.count(":") == 1 and not host.startswith("["):
            maybe_host, maybe_port = host.rsplit(":", 1)
            if maybe_port.isdigit():
                host = maybe_host
        host = host.strip("[]")
    return host.strip()


def resolve_host_for_region_lookup(host: str) -> str:
    host = normalize_host_value(host)
    if not host:
        return ""
    try:
        socket.inet_pton(socket.AF_INET, host)
        return host
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return host
    except OSError:
        pass
    try:
        info = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        for item in info:
            addr = item[4][0]
            if addr:
                return addr
    except Exception:
        return host
    return host


def country_text_to_code(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    return COUNTRY_NAME_TO_CODE.get(raw) or COUNTRY_NAME_TO_CODE.get(raw.lower(), "")


def infer_country_code_from_node_name(name: str) -> str:
    text = str(name or "").strip().lower()
    if not text:
        return ""
    for key, code in COUNTRY_NAME_TO_CODE.items():
        if key and key.lower() in text:
            return code
    return ""


def country_code_to_flag(country_code: str) -> str:
    code = str(country_code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(ord(char) - ord("A") + 0x1F1E6) for char in code)


def country_code_to_badge(country_code: str) -> str:
    code = str(country_code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return code


def lookup_region_by_host(host: str, timeout: float = 1.6) -> dict[str, Any]:
    ip = resolve_host_for_region_lookup(host)
    if not ip:
        return {"code": "", "flag": "", "badge": "", "flag_codes": [], "label": ""}
    if ip in _IP_REGION_CACHE:
        return dict(_IP_REGION_CACHE[ip])
    result: dict[str, Any]
    try:
        url = f"http://ip-api.com/json/{urllib.parse.quote(ip)}?fields=status,countryCode,country,regionName"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        if data.get("status") == "success" and data.get("countryCode"):
            code = str(data.get("countryCode") or "").strip().upper()
            region = str(data.get("regionName") or "").strip()
            country = COUNTRY_NAME_MAP.get(code, str(data.get("country") or code))
            result = {
                "code": code,
                "flag": country_code_to_flag(code),
                "badge": country_code_to_badge(code),
                "flag_codes": [code.lower()],
                "label": f"{country} {region}".strip(),
            }
        else:
            result = {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": ip}
    except Exception:
        result = {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": ip}
    _IP_REGION_CACHE[ip] = result
    return dict(result)


def lookup_country_code_by_host(host: str, timeout: float = 1.6) -> str:
    return str(lookup_region_by_host(host, timeout=timeout).get("code") or "").strip().upper()


def node_country_code(node: dict | object | None, *, allow_lookup: bool = False, allow_name_infer: bool = True) -> str:
    manual_code = country_text_to_code(_node_value(node, "manual_country_code"))
    if manual_code:
        return manual_code
    manual_label = country_text_to_code(_node_value(node, "manual_region_label"))
    if manual_label:
        return manual_label
    auto_code = country_text_to_code(_node_value(node, "country_code"))
    if auto_code:
        return auto_code
    auto_label = country_text_to_code(_node_value(node, "country") or _node_value(node, "region_label"))
    if auto_label:
        return auto_label
    if allow_name_infer:
        inferred = infer_country_code_from_node_name(_node_value(node, "name"))
        if inferred:
            return inferred
    if allow_lookup:
        looked_up = lookup_country_code_by_host(_node_value(node, "ip"))
        if looked_up:
            return looked_up
    return ""


def node_flag_emoji(node: dict | object | None, *, allow_lookup: bool = False, allow_name_infer: bool = True) -> str:
    return country_code_to_flag(node_country_code(node, allow_lookup=allow_lookup, allow_name_infer=allow_name_infer))


def region_from_node(node: dict | object | None, *, allow_lookup: bool = True, allow_name_infer: bool = True) -> dict[str, Any]:
    code = node_country_code(node, allow_lookup=False, allow_name_infer=allow_name_infer)
    manual_label = _node_value(node, "manual_region_label")
    if code:
        return {
            "code": code,
            "flag": country_code_to_flag(code),
            "badge": country_code_to_badge(code),
            "flag_codes": [code.lower()],
            "label": manual_label or COUNTRY_NAME_MAP.get(code, code),
        }
    if manual_label:
        return {"code": "", "flag": "📍", "badge": "", "flag_codes": [], "label": manual_label}
    if allow_lookup:
        return lookup_region_by_host(_node_value(node, "ip"))
    return {"code": "", "flag": "", "badge": "", "flag_codes": [], "label": ""}


def chain_display_region(front_node: dict | object | None, backend_node: dict | object | None) -> dict[str, Any]:
    # 列表展示链式节点时，只显示落地端（backend）的国家/地区，避免入口国旗误导实际出口。
    backend_region = region_from_node(backend_node, allow_lookup=True)
    if backend_region.get("code") or backend_region.get("label"):
        return {**backend_region, "label": f"落地端：{backend_region.get('label') or backend_region.get('code')}"}
    return {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": "落地端未知"}


def vless_remark_for_node(node: dict | object | None, fallback_name: str = "", *, allow_lookup: bool = False, allow_name_infer: bool = True, region_source_node: dict | object | None = None) -> str:
    name = _node_value(node, "name") or str(fallback_name or "").strip()
    source = region_source_node if region_source_node is not None else node
    flag = node_flag_emoji(source, allow_lookup=allow_lookup, allow_name_infer=allow_name_infer)
    if flag and name:
        return f"{flag} {name}"
    return name


def replace_vless_fragment(link: str, remark: str) -> str:
    raw = str(link or "").strip()
    if not raw.startswith("vless://") or not remark:
        return raw
    parsed = urllib.parse.urlsplit(raw)
    encoded_remark = urllib.parse.quote(remark, safe="")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, encoded_remark))
