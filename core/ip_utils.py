"""Utilities for extracting and validating client IP addresses."""

from __future__ import annotations

import ipaddress


def normalize_client_ip(value: str | None) -> str | None:
    """Return a normalized IP string, or None when invalid/missing."""
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def extract_client_ip(meta: dict) -> str | None:
    """
    Extract the left-most client IP from forwarding headers and validate it.

    Returns None when no valid IP is present.
    """
    x_forwarded_for = meta.get("HTTP_X_FORWARDED_FOR")
    if isinstance(x_forwarded_for, str) and x_forwarded_for.strip():
        first = x_forwarded_for.split(",")[0].strip()
        normalized = normalize_client_ip(first)
        if normalized:
            return normalized

    remote_addr = meta.get("REMOTE_ADDR")
    if isinstance(remote_addr, str):
        return normalize_client_ip(remote_addr)
    return None
