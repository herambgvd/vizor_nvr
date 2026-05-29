# =============================================================================
# SSRF guard for outbound requests (webhooks, etc.)
# =============================================================================
#
# Linkage rules let operators configure arbitrary webhook URLs. Without
# validation, a URL like http://169.254.169.254/ (cloud metadata) or
# http://127.0.0.1:8000/ could be used to pivot against internal services.
#
# validate_outbound_url() enforces:
#   - scheme is http or https
#   - the host does not resolve to a private / loopback / link-local /
#     reserved / multicast / unspecified address (checked across ALL resolved
#     A/AAAA records, so a hostname that resolves to a mix is rejected)
#   - optional explicit host allow-list (exact host match, case-insensitive)
# =============================================================================

import ipaddress
import logging
import socket
from typing import Optional, Sequence
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


class OutboundURLError(ValueError):
    """Raised when an outbound URL fails SSRF validation."""


def _is_blocked_address(ip: str) -> bool:
    """True if the IP falls in a range we must never let webhooks reach."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable → treat as unsafe
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_outbound_url(
    url: str,
    allowed_hosts: Optional[Sequence[str]] = None,
) -> str:
    """Validate that *url* is safe to fetch from the server.

    Returns the URL unchanged on success; raises OutboundURLError otherwise.
    DNS resolution is performed synchronously — call from a thread when on an
    event loop hot path.
    """
    if not url or not isinstance(url, str):
        raise OutboundURLError("Webhook URL is empty")

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise OutboundURLError(f"Unsupported URL scheme: {parts.scheme!r}")

    host = parts.hostname
    if not host:
        raise OutboundURLError("Webhook URL has no host")

    if allowed_hosts:
        allow = {h.strip().lower() for h in allowed_hosts if h and h.strip()}
        if allow and host.lower() not in allow:
            raise OutboundURLError(f"Host {host!r} is not in the webhook allow-list")

    # Resolve every address the host maps to and reject if ANY is internal.
    try:
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise OutboundURLError(f"Could not resolve host {host!r}: {e}")

    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise OutboundURLError(f"Host {host!r} resolved to no addresses")

    for ip in addresses:
        if _is_blocked_address(ip):
            raise OutboundURLError(
                f"Host {host!r} resolves to a disallowed address ({ip})"
            )

    return url
