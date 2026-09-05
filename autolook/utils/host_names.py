"""Resolve teammate display names from IP or hostname aliases."""

import re
import socket
from functools import lru_cache
from pathlib import Path

_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def looks_like_ip(value: str) -> bool:
    return bool(value and _IP_RE.match(value.strip()))


@lru_cache(maxsize=256)
def hostname_to_ip(host: str) -> str:
    """Resolve hostname to IPv4. Returns empty string on failure."""
    if not host:
        return ""
    host = host.strip()
    if looks_like_ip(host):
        return host
    try:
        return socket.gethostbyname(host)
    except OSError:
        return ""


def normalize_key(value: str) -> str:
    return (value or "").strip().lower()


def build_recording_ip_index(recording_path: Path | None) -> dict[str, str]:
    """Map lowercase hostname hints from filenames under IP folders.

    Net Monitor stores recordings as:
      recordings/<ip>/Administrator_<date>....mkv
    Aliases often use IP keys; WEBLOG uses hostnames. This helper is used
    when we also store host->ip from folder names in config.
    """
    if not recording_path or not recording_path.exists():
        return {}
    # Return IP folder names for Settings "Load" convenience
    ips = {}
    for child in recording_path.iterdir():
        if child.is_dir() and looks_like_ip(child.name):
            ips[child.name] = child.name
    return ips


@lru_cache(maxsize=256)
def ip_to_hostname(ip: str) -> str:
    """Reverse-resolve IP to hostname. Returns empty string on failure."""
    if not ip or not looks_like_ip(ip):
        return ""
    try:
        return socket.gethostbyaddr(ip.strip())[0]
    except OSError:
        return ""


def resolve_display_name(host: str, aliases: dict[str, str]) -> str:
    """Return mapped name for a Net Monitor HOST value.

    Aliases keys can be IPs (192.168.1.10) or hostnames (DESKTOP-xxx).
    Matching order: exact host, resolved IP, reverse-DNS of IP aliases.
    """
    if not host or not aliases:
        return ""

    host = host.strip()
    lookup = {normalize_key(k): v for k, v in aliases.items() if k and v}

    # Expand IP aliases with reverse-DNS hostnames when available
    for key, name in list(aliases.items()):
        if looks_like_ip(key):
            hname = ip_to_hostname(key)
            if hname:
                lookup.setdefault(normalize_key(hname), name)
                # Also short name without domain
                short = hname.split(".")[0]
                lookup.setdefault(normalize_key(short), name)

    if normalize_key(host) in lookup:
        return lookup[normalize_key(host)]

    ip = hostname_to_ip(host)
    if ip and normalize_key(ip) in lookup:
        return lookup[normalize_key(ip)]

    return ""


def format_user_label(host: str, user: str, aliases: dict[str, str]) -> str:
    """Name for table display: mapped name, else original user."""
    name = resolve_display_name(host, aliases)
    if name:
        return name
    return user or ""
