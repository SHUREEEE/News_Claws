from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrlError(ValueError):
    pass


def validate_public_ip(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if not ip.is_global:
        raise UnsafeUrlError(f"Non-public source address is not allowed: {address}")


def validate_public_http_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UnsafeUrlError("Only absolute http/https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeUrlError("Credentials in source URLs are not allowed")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError("Loopback hosts are not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parts.port or 443)}
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Source host cannot be resolved: {host}") from exc
    for address in addresses:
        validate_public_ip(address)
    return url
