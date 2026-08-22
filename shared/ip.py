"""Utilities for extracting and validating client IP addresses."""

from __future__ import annotations

import ipaddress

from django.http import HttpRequest


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


def client_ip(request: HttpRequest | None) -> str | None:
    """The caller's IP, best effort, and this never raises.

    The callers are audit and notice paths that run *beside* the work rather
    than as part of it: a sign-in, a signup notice.  A malformed ``META`` must
    not fail the sign-in it is only there to record, so every failure reads as
    "no IP".  ``None`` covers both "no request" and "could not tell"; a caller
    that needs a word for the second writes ``client_ip(request) or
    "unknown"``.
    """
    if request is None:
        return None
    try:
        return extract_client_ip(request.META)
    except Exception:  # noqa: BLE001 — reading an IP is never fatal to the caller
        return None
