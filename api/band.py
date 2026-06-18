"""Date coercion shared by the result formatters.

(This module also used to compute the IN FORCE band's timeline-rail geometry;
that was superseded by the attestation rail — see ``core.verification``.)
"""

from __future__ import annotations

from datetime import date
from typing import Any


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
