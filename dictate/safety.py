from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Host suffixes that look LAN-only and should never resolve out to the
# internet. .internal is used by AWS/GCP/k8s service meshes, .local is mDNS.
_BLOCKED_HOST_SUFFIXES = (".internal", ".local")


def validate_backend_url(url: str) -> None:
    """Raise ValueError when a backend URL points somewhere we won't talk to.

    Defends against a hostile config/backends.yaml redirecting health pings or
    cleanup POSTs at internal cloud metadata services, link-local addresses,
    multicast ranges, or non-HTTP schemes that httpx still understands.

    Loopback (127.0.0.0/8, ::1, "localhost") and ordinary RFC1918 LAN
    addresses are allowed because users legitimately self-host (Ollama,
    llama.cpp, LM Studio) on the local machine or a home server.
    """
    if not isinstance(url, str) or not url:
        raise ValueError("backend url is empty")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(f"backend url scheme '{parsed.scheme}' not allowed")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("backend url has no host")

    for suffix in _BLOCKED_HOST_SUFFIXES:
        if host.endswith(suffix):
            raise ValueError(f"backend host '{host}' uses blocked suffix '{suffix}'")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return

    if ip.is_loopback:
        return
    if ip.is_link_local:
        raise ValueError(f"backend host '{host}' is link-local")
    if ip.is_multicast:
        raise ValueError(f"backend host '{host}' is multicast")
    if ip.is_unspecified:
        raise ValueError(f"backend host '{host}' is unspecified (0.0.0.0/::)")
    if ip.is_reserved:
        raise ValueError(f"backend host '{host}' is in a reserved range")
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("100.64.0.0/10"):
        raise ValueError(f"backend host '{host}' is in CGNAT range")
