"""Staff-only traction dashboard.

Deliberately not in the Django admin.  The admin lists rows; this page answers
"did the numbers move", which is a different question and wants a different
shape — headline totals first, per-day and cumulative charts second.

Access is ``is_staff``, checked with ``user_passes_test`` rather than
``staff_member_required`` so a signed-out visitor lands on the normal login
page instead of the admin one.  The page is also disallowed in ``robots.txt``.
"""

from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.insights import (
    CHART_HEIGHT,
    CHART_WIDTH,
    DEFAULT_WINDOW_DAYS,
    collect_metrics,
    conversion_rates,
    edition_requests,
    top_queries,
)

#: Windows offered by the range control.  Fixed choices rather than a free
#: number: the bar width is computed against a known canvas, and a 3000-day
#: window would render sub-pixel bars.
WINDOW_CHOICES: tuple[int, ...] = (30, 90, 365)


def _resolve_window(raw: str | None) -> int:
    """The requested window, or the default when it is absent or not offered."""
    try:
        days = int(raw or "")
    except ValueError:
        return DEFAULT_WINDOW_DAYS
    return days if days in WINDOW_CHOICES else DEFAULT_WINDOW_DAYS


def _is_staff(user: Any) -> bool:
    """Gate predicate. ``Any`` because the check also sees ``AnonymousUser``."""
    return bool(getattr(user, "is_active", False) and getattr(user, "is_staff", False))


@user_passes_test(_is_staff)
def insights(request: HttpRequest) -> HttpResponse:
    """Traction numbers: totals, per-day bars, cumulative lines."""
    days = _resolve_window(request.GET.get("days"))
    metrics = collect_metrics(days)
    context: dict[str, Any] = {
        "metrics": metrics,
        "rates": conversion_rates(metrics),
        "queries": top_queries(days=days),
        "requests": edition_requests(days=days),
        "days": days,
        "window_choices": WINDOW_CHOICES,
        "chart_width": CHART_WIDTH,
        "chart_height": CHART_HEIGHT,
    }
    return render(request, "insights.html", context)
