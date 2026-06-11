"""Region helpers — with IP geolocation for natxyz."""
from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.parse
from urllib.parse import urlparse, urlunparse, quote

# Simple in-memory cache for geolocation results
_CACHE_FILE = "/opt/natxyz/data/geo_cache.json"
_cache: dict[str, dict] = {}


def _load_cache():
    global _cache
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE) as f:
                _cache = json.load(f)
    except Exception:
        _cache = {}


def _save_cache():
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w") as f:
            json.dump(_cache, f)
    except Exception:
        pass


_load_cache()


def _geo_lookup(ip: str) -> dict | None:
    """Look up country for IP using ipapi.co (free, no key, 1000 req/day)."""
    if ip in _cache:
        entry = _cache[ip]
        # Cache for 7 days
        if time.time() - entry.get("ts", 0) < 604800:
            return entry.get("data")
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://ipapi.co/{ip}/json/",
            headers={"User-Agent": "natxyz/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            if data.get("error"):
                _cache[ip] = {"ts": time.time(), "data": None}
                _save_cache()
                return None
            result = {
                "code": (data.get("country_code") or "").upper(),
                "label": data.get("country_name") or "",
                "city": data.get("city") or "",
            }
            _cache[ip] = {"ts": time.time(), "data": result}
            _save_cache()
            return result
    except Exception:
        _cache[ip] = {"ts": time.time(), "data": None}
        _save_cache()
        return None


def _is_private_ip(ip_str: str) -> bool:
    try:
        return ipaddress.ip_address(ip_str).is_private
    except ValueError:
        return False


_COUNTRY_EMOJI: dict[str, str] = {
    "HK": "🇭🇰", "JP": "🇯🇵", "KR": "🇰🇷", "US": "🇺🇸",
    "TW": "🇹🇼", "SG": "🇸🇬", "TR": "🇹🇷", "AU": "🇦🇺",
    "CN": "🇨🇳", "MY": "🇲🇾", "DE": "🇩🇪", "GB": "🇬🇧",
    "FR": "🇫🇷", "NL": "🇳🇱", "CA": "🇨🇦", "BR": "🇧🇷",
    "IN": "🇮🇳", "RU": "🇷🇺", "AE": "🇦🇪", "SA": "🇸🇦",
    "TH": "🇹🇭", "VN": "🇻🇳", "PH": "🇵🇭", "ID": "🇮🇩",
    "KH": "🇰🇭", "MM": "🇲🇲", "LA": "🇱🇦", "BD": "🇧🇩",
    "PK": "🇵🇰", "IR": "🇮🇷", "IQ": "🇮🇶", "IL": "🇮🇱",
    "EG": "🇪🇬", "ZA": "🇿🇦", "NG": "🇳🇬", "KE": "🇰🇪",
    "AR": "🇦🇷", "CL": "🇨🇱", "MX": "🇲🇽", "PE": "🇵🇪",
    "CO": "🇨🇴", "VE": "🇻🇪", "UA": "🇺🇦", "PL": "🇵🇱",
    "IT": "🇮🇹", "ES": "🇪🇸", "PT": "🇵🇹", "SE": "🇸🇪",
    "NO": "🇳🇴", "DK": "🇩🇰", "FI": "🇫🇮", "IS": "🇮🇸",
    "EE": "🇪🇪", "LV": "🇱🇻", "LT": "🇱🇹", "CZ": "🇨🇿",
    "SK": "🇸🇰", "HU": "🇭🇺", "RO": "🇷🇴", "BG": "🇧🇬",
    "HR": "🇭🇷", "SI": "🇸🇮", "AT": "🇦🇹", "CH": "🇨🇭",
    "BE": "🇧🇪", "LU": "🇱🇺", "IE": "🇮🇪", "GR": "🇬🇷",
    "MT": "🇲🇹", "CY": "🇨🇾", "KZ": "🇰🇿", "UZ": "🇺🇿",
    "AZ": "🇦🇿", "GE": "🇬🇪", "AM": "🇦🇲", "BY": "🇧🇾",
    "MD": "🇲🇩", "AL": "🇦🇱", "MK": "🇲🇰", "RS": "🇷🇸",
    "BA": "🇧🇦", "ME": "🇲🇪", "XK": "🇽🇰",
}


_COUNTRY_LABELS: dict[str, str] = {
    "HK": "香港", "JP": "日本", "KR": "韩国", "US": "美国",
    "TW": "台湾", "SG": "新加坡", "TR": "土耳其", "AU": "澳大利亚",
    "CN": "中国", "MY": "马来西亚", "DE": "德国", "GB": "英国",
    "FR": "法国", "NL": "荷兰", "CA": "加拿大", "BR": "巴西",
    "IN": "印度", "RU": "俄罗斯", "AE": "阿联酋", "SA": "沙特",
    "TH": "泰国", "VN": "越南", "PH": "菲律宾", "ID": "印尼",
    "KH": "柬埔寨", "MM": "缅甸", "LA": "老挝", "BD": "孟加拉",
    "PK": "巴基斯坦", "IR": "伊朗", "IQ": "伊拉克", "IL": "以色列",
    "EG": "埃及", "ZA": "南非", "NG": "尼日利亚", "KE": "肯尼亚",
    "AR": "阿根廷", "CL": "智利", "MX": "墨西哥", "PE": "秘鲁",
    "CO": "哥伦比亚", "VE": "委内瑞拉", "UA": "乌克兰", "PL": "波兰",
    "IT": "意大利", "ES": "西班牙", "PT": "葡萄牙", "SE": "瑞典",
    "NO": "挪威", "DK": "丹麦", "FI": "芬兰", "IS": "冰岛",
    "EE": "爱沙尼亚", "LV": "拉脱维亚", "LT": "立陶宛",
    "CZ": "捷克", "SK": "斯洛伐克", "HU": "匈牙利", "RO": "罗马尼亚",
    "BG": "保加利亚", "HR": "克罗地亚", "SI": "斯洛文尼亚",
    "AT": "奥地利", "CH": "瑞士", "BE": "比利时", "LU": "卢森堡",
    "IE": "爱尔兰", "GR": "希腊", "MT": "马耳他", "CY": "塞浦路斯",
    "KZ": "哈萨克斯坦", "UZ": "乌兹别克斯坦", "AZ": "阿塞拜疆",
    "GE": "格鲁吉亚", "AM": "亚美尼亚", "BY": "白俄罗斯",
    "MD": "摩尔多瓦", "AL": "阿尔巴尼亚", "MK": "北马其顿",
    "RS": "塞尔维亚", "BA": "波黑", "ME": "黑山", "XK": "科索沃",
}

_HOST_COUNTRY_OVERRIDES: dict[str, str] = {
    # Common VPS hostname patterns → country
    "hinet": "TW",
    "akile": "JP",
    "iij": "JP",
    "vultr": "US",
    "digitalocean": "US",
    "linode": "US",
    "hetzner": "DE",
    "ovh": "FR",
    "scaleway": "FR",
    "contabo": "DE",
    "netcup": "DE",
    "oracle": "US",
    "aws": "US",
    "azure": "US",
    "gcp": "US",
    "alibabacloud": "CN",
    "tencent": "CN",
    "huawei": "CN",
    "buyvm": "US",
    "racknerd": "US",
    "colocrossing": "US",
    "psychz": "US",
    "dmit": "US",
    "misaka": "JP",
    "xtom": "JP",
    "greencloud": "US",
    "hosthatch": "US",
    "liteserver": "NL",
    "time4vps": "LT",
    "servarica": "CA",
    "privex": "US",
}


def _detect_country_from_host(host: str) -> str | None:
    """Try to detect country from hostname patterns."""
    host_lower = host.lower()
    for keyword, code in _HOST_COUNTRY_OVERRIDES.items():
        if keyword in host_lower:
            return code
    return None


def _get(row, key, default=None):
    """Safe get for both dict and sqlite3.Row."""
    try:
        return row.get(key, default)
    except AttributeError:
        try:
            return row[key]
        except (KeyError, IndexError):
            return default


def replace_vless_fragment(link: str, name: str) -> str:
    """Replace the fragment of a vless:// URL with an encoded remark."""
    if not link or not name:
        return link
    try:
        parsed = urlparse(link)
        fragment = quote(name, safe="")
        replaced = parsed._replace(fragment=fragment)
        return urlunparse(replaced)
    except Exception:
        return link


def vless_remark_for_node(
    node,
    *args,
    allow_lookup: bool = False,
    region_source_node=None,
) -> str:
    """Generate a remark string for a vless link from node data."""
    name = str(_get(node, "name") or _get(node, "node_id") or "")
    region = region_from_node(node, allow_lookup=allow_lookup) if allow_lookup else {"label": ""}
    code = _get(region, "code", "")
    badge = _get(region, "badge", "")
    if code and badge:
        return f"{badge} {code} | {name}"
    return name


def lookup_region_by_host(host: str):
    """Look up region info by hostname/IP with geolocation."""
    if not host:
        return {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": ""}

    # Try hostname patterns first
    country_code = _detect_country_from_host(host)
    
    # Fall back to IP geolocation for public IPs
    if not country_code and not _is_private_ip(host):
        geo = _geo_lookup(host)
        if geo:
            country_code = geo.get("code", "")

    if country_code and country_code in _COUNTRY_EMOJI:
        return {
            "code": country_code,
            "flag": _COUNTRY_EMOJI[country_code],
            "badge": _COUNTRY_EMOJI[country_code],
            "flag_codes": [country_code.lower()],
            "label": _COUNTRY_LABELS.get(country_code, country_code),
        }

    return {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": ""}


def region_from_node(node=None, *, allow_lookup: bool = False):
    """Return region info dict for a node."""
    if not node:
        return {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": ""}

    # Check manual override
    manual_code = str(_get(node, "manual_country_code") or "").strip().upper()
    manual_label = str(_get(node, "manual_region_label") or "").strip()
    if manual_code and manual_code in _COUNTRY_EMOJI:
        return {
            "code": manual_code,
            "flag": _COUNTRY_EMOJI[manual_code],
            "badge": _COUNTRY_EMOJI[manual_code],
            "flag_codes": [manual_code.lower()],
            "label": manual_label or _COUNTRY_LABELS.get(manual_code, manual_code),
        }

    host = str(_get(node, "ip") or "").strip()
    if host:
        return lookup_region_by_host(host)
    return {"code": "", "flag": "🌐", "badge": "IP", "flag_codes": [], "label": ""}


def country_code_to_badge(country_code: str) -> str:
    """Map country code to emoji flag."""
    return _COUNTRY_EMOJI.get(country_code.upper(), "🌐")


def country_code_to_flag(country_code: str) -> str:
    """Map country code to emoji flag."""
    return country_code_to_badge(country_code)
