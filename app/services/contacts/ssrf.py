"""SSRF guards for operator-supplied and discovered fetch URLs."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a URL must not be fetched."""


_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.google",
    }
)


def assert_public_http_url(url: str) -> None:
    """Reject non-http(s), loopback, private, link-local, and metadata destinations."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Unsupported URL scheme: {parsed.scheme!r}")
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host:
        raise UnsafeUrlError("URL missing host")
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        raise UnsafeUrlError(f"Blocked host: {host}")
    if host.endswith(".local") or host.endswith(".internal"):
        raise UnsafeUrlError(f"Blocked host: {host}")

    # Literal IP in the URL
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        _reject_bad_ip(ip)

    # Resolve and re-check (mitigates DNS rebinding to private ranges)
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"DNS resolution failed for {host}") from exc
    for info in infos:
        sockaddr = info[4]
        try:
            resolved = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        _reject_bad_ip(resolved)


def _reject_bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise UnsafeUrlError(f"Blocked address: {ip}")


def is_safe_public_http_url(url: str) -> bool:
    try:
        assert_public_http_url(url)
        return True
    except UnsafeUrlError:
        return False
