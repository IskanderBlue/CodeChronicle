"""Engagement-event recording — the write side of :class:`EngagementEvent`.

Every helper here is *best-effort*: a tracking failure must never break the
page or the search that triggered it, so writes are wrapped and swallowed
(mirroring the ``SearchHistory`` write in ``services.search_service``).  The
caller passes the already-resolved target; identity (user vs. anonymous IP)
is derived from the request the same way the search path does it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from coloured_logger import Logger
from django.http import HttpRequest
from django.urls import Resolver404, resolve

from core.ip_utils import extract_client_ip
from core.models import EngagementEvent

logger = Logger(__name__)


def _coerce_search_id(value: Any) -> int | None:
    """Parse a search id that arrives as a query-string/body string.

    Returns ``None`` for anything that isn't a positive integer so a bogus
    client-supplied value never raises — the FK just stays unset.
    """
    try:
        sid = int(value)
    except (TypeError, ValueError):
        return None
    return sid if sid > 0 else None


def arrival_context(request: HttpRequest) -> dict[str, str]:
    """How the reader reached this page, as two keys for an event's context.

    A consultant follows links: from a search, from a contents page, from a
    provision they were already reading.  Somebody enumerating the corpus
    arrives **cold** — no referrer at all — or from container pages only,
    because ``CONTENTS_THRESHOLD`` made those the one place the deep links
    exist.  That is a shape, not a quantity, so it has no ceiling problem: no
    amount of ordinary reading produces 3,000 cold arrivals in id order.

    Two keys, each saying one thing.  ``arrival`` is ``cold`` / ``internal`` /
    ``external``; ``from`` is the **route name** of the page linked here, and
    only for an internal arrival.

    **The URL is never stored.** A route name carries no query string and no
    provision identity, so this records the shape of a walk without recording
    anybody's reading list — which the ledger already holds, under a rule the
    Privacy Policy states. A referrer from outside can carry somebody else's
    search terms, and there is no version of this signal that needs them.
    """
    referer = request.headers.get("Referer", "")
    if not referer:
        return {"arrival": "cold"}
    parsed = urlparse(referer)
    if parsed.netloc and parsed.netloc != request.get_host():
        return {"arrival": "external"}
    try:
        match = resolve(parsed.path)
    except Resolver404:
        # Same host, no route: a stale link, or a path this deployment no
        # longer serves.  Still an internal arrival, with nothing to name.
        return {"arrival": "internal", "from": ""}
    return {"arrival": "internal", "from": match.url_name or ""}


def record_event(
    request: HttpRequest,
    *,
    event_type: str,
    object_type: str = "",
    object_id: int | None = None,
    search_id: Any = None,
    context: dict[str, Any] | None = None,
) -> EngagementEvent | None:
    """Write one :class:`EngagementEvent`, swallowing any failure.

    Identity follows the search convention: the FK to ``user`` for an
    authenticated request, otherwise the client ``ip_address``.  ``search_id``
    may be a raw string (it usually arrives via a query param) — it's coerced
    and silently dropped if invalid.  Returns the created row, or ``None`` if
    the write failed (logged, never raised).
    """
    try:
        # Attribute access (not getattr) so django-stubs narrows away
        # AnonymousUser via the Literal[False] is_authenticated — the FK takes
        # User | None.
        user = request.user if request.user.is_authenticated else None
        ip = extract_client_ip(request.META) if user is None else None
        return EngagementEvent.objects.create(
            user=user,
            ip_address=ip,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            search_id=_coerce_search_id(search_id),
            context=context or {},
        )
    except Exception as e:  # noqa: BLE001 — tracking is never fatal
        logger.error("Error recording engagement event (%s): %s", event_type, e)
        return None
