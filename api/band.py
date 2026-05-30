"""Geometry for the IN FORCE band's timeline rail.

The viewer's hero element shows an in-force period as a coloured span on a
horizontal rail, with a tick marking the user's query date.  This module
turns three dates — the provision version's effective date, the date it
ceased to be in force, and the query date — into rail positions expressed as
percentages, plus a boolean for whether the query date is covered.

Computing this server-side (rather than in the template) keeps the logic
unit-testable and the markup declarative.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Fraction of the from→until window added as padding on each side so the
# in-force span sits inset from the rail edges rather than flush against them.
_WINDOW_PAD = 0.15


def parse_iso_date(value: Any) -> date | None:
    """Coerce a value to a ``date``; return None if it can't be parsed.

    Accepts ``date`` objects and ISO ``YYYY-MM-DD`` strings (extra time
    components are ignored).
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def compute_band_geometry(
    from_date: date | None,
    until_date: date | None,
    query_date: date | None,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Return rail positions for the IN FORCE band, or None if unanchored.

    Args:
        from_date: When the version came into force (the span's left edge).
        until_date: When it ceased to be in force. ``None`` means open-ended
            (still current); ``today`` is used as the visual right edge.
        query_date: The user's as-of date. ``None`` hides the tick.
        today: Override for the current date (testing).

    Returns:
        A dict with ``span_left_pct`` / ``span_width_pct`` (the in-force
        span), ``tick_pct`` (query-date marker, or None), ``covered``
        (bool, or None when no query date), and ``open_ended``. Returns
        ``None`` when there is no ``from_date`` to anchor the rail.

    The rail window spans ``[min(from, query) - pad, max(until, query) +
    pad]`` so a query date outside the in-force period still lands on the
    rail — in which case ``covered`` is False.
    """
    if from_date is None:
        return None

    today = today or date.today()
    open_ended = until_date is None
    until = until_date or today
    # Guard against inverted ranges (bad data): never let the span go negative.
    if until < from_date:
        until = from_date

    anchors = [from_date, until]
    if query_date is not None:
        anchors.append(query_date)
    lo, hi = min(anchors), max(anchors)

    total_days = (hi - lo).days or 1
    pad = max(round(total_days * _WINDOW_PAD), 1)
    window_start = lo - timedelta(days=pad)
    window_span = (hi + timedelta(days=pad) - window_start).days

    def pct(d: date) -> float:
        return round((d - window_start).days / window_span * 100, 2)

    left = pct(from_date)
    right = pct(until)

    covered: bool | None = None
    tick_pct: float | None = None
    if query_date is not None:
        tick_pct = pct(query_date)
        # In force over [effective, ineffective); open-ended periods (no
        # ineffective date) have no upper bound. Guard on `until_date is
        # None` rather than `open_ended` so the type checker narrows it.
        covered = from_date <= query_date and (
            until_date is None or query_date < until_date
        )

    return {
        "span_left_pct": left,
        "span_width_pct": round(right - left, 2),
        "tick_pct": tick_pct,
        "covered": covered,
        "open_ended": open_ended,
    }
