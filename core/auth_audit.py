"""Authentication audit — the write side of :class:`core.models.AuthEvent`.

Receivers on Django's auth signals record each login, logout, and failed login
as an :class:`~core.models.AuthEvent` row.  Like ``core.events`` these writes
are *best-effort*: an audit failure must never block or break authentication, so
every receiver swallows its own exceptions.  The signals fire regardless of the
authentication backend, so allauth's email login is covered without hooking
allauth-specific signals.

Wired for side effects in ``CoreConfig.ready`` (``core.apps``).
"""

from __future__ import annotations

from typing import Any

from coloured_logger import Logger
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver
from django.http import HttpRequest

from core.ip_utils import extract_client_ip
from core.models import AuthEvent

logger = Logger(__name__)


def _ip(request: HttpRequest | None) -> str | None:
    """Best-effort client IP — never raises (auth must not break on a bad META)."""
    if request is None:
        return None
    try:
        return extract_client_ip(request.META)
    except Exception:  # noqa: BLE001 — IP parsing is never fatal to auth
        return None


def _record(
    event_type: str,
    *,
    user: Any = None,
    email: str = "",
    request: HttpRequest | None = None,
) -> None:
    """Write one :class:`AuthEvent`, swallowing any failure.

    ``user`` is stored only when it is a real authenticated user (a logout can
    arrive with ``AnonymousUser``/``None``); the presented ``email`` is kept
    regardless so a failed attempt — which has no user — is still attributable.
    """
    try:
        real_user = user if (user is not None and user.is_authenticated) else None
        AuthEvent.objects.create(
            user=real_user,
            email=email or (getattr(user, "email", "") or ""),
            ip_address=_ip(request),
            event_type=event_type,
        )
    except Exception as e:  # noqa: BLE001 — auditing is never fatal
        logger.error("Error recording auth event (%s): %s", event_type, e)


@receiver(user_logged_in)
def handle_user_logged_in(sender, request=None, user=None, **kwargs):
    _record(AuthEvent.EventType.LOGIN, user=user, request=request)


@receiver(user_logged_out)
def handle_user_logged_out(sender, request=None, user=None, **kwargs):
    _record(AuthEvent.EventType.LOGOUT, user=user, request=request)


@receiver(user_login_failed)
def handle_user_login_failed(sender, credentials=None, request=None, **kwargs):
    # ``credentials`` is Django's password-scrubbed copy of the authenticate()
    # kwargs; the identifier key is ``username`` for the model backend and
    # ``email`` for allauth's — capture whichever is present.
    creds = credentials or {}
    email = creds.get("email") or creds.get("username") or ""
    _record(AuthEvent.EventType.LOGIN_FAILED, email=email, request=request)
