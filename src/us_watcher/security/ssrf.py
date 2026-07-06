"""SSRF / URL validation for any outbound fetch of external references (spec §29).

Blocks non-http(s) schemes, internal/private/loopback/link-local IP ranges, and
the cloud metadata endpoint. Use :func:`is_safe_url` before fetching any
user/article-supplied URL.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}


def is_safe_url(url: str) -> tuple[bool, str]:
    """Return (ok, reason). ``ok=False`` means do NOT fetch it."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "unparseable URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"blocked scheme: {parsed.scheme!r}"
    host = parsed.hostname
    if not host:
        return False, "missing host"
    if host.lower() in _BLOCKED_HOSTS:
        return False, "blocked host"
    # Resolve and reject private/loopback/link-local/metadata addresses.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "DNS resolution failed"
    for info in infos:
        ip_str = info[4][0]
        if ip_str in _METADATA_IPS:
            return False, "cloud metadata endpoint"
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False, f"non-public address: {ip_str}"
    return True, "ok"
