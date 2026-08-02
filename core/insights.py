"""The traction numbers, and the geometry to draw them.

One module, deliberately, for two jobs that must not drift apart: what a metric
counts, and what its chart shows.  A dashboard whose headline says "412" while
its bars sum to 380 is worse than no dashboard, so both come from the same
per-day series here rather than from two queries written months apart.

Three questions this page exists to answer, in order:

1. Are people finding it?          -> searches, by anonymous visitors
2. Does the wall convert?          -> signups per rate-limit block
3. Does anyone pay?                -> active subscriptions

Everything else on the page is context for those three.  Counts are *events*,
not states, with one exception (``subscriptions``) that is called out where it
is built — a state has no per-day history to draw, and pretending otherwise
would draw a shape the data does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from django.db.models import Count, QuerySet
from django.db.models.functions import TruncDate
from django.utils import timezone
from djstripe.models import Subscription

from core.models import AuthEvent, EditionRequest, EngagementEvent, SearchHistory, User

#: Default width of the time window, in days.  Long enough that a weekly rhythm
#: is visible, short enough that one bar is still wide enough to hover.
DEFAULT_WINDOW_DAYS = 90

#: Chart canvas, in SVG user units.  Fixed rather than fluid so the bar width
#: and the 2px inter-bar gap are computed once, in Python, against a known
#: canvas; the rendered element scales by viewBox and keeps its aspect.
CHART_WIDTH = 720
CHART_HEIGHT = 132

#: Gap between adjacent bars, in the same units.  From the house mark spec: a
#: 2px surface gap between adjacent fills, so a run of non-zero days reads as
#: separate days rather than one block.
BAR_GAP = 2


@dataclass(frozen=True)
class Bar:
    """One day's column in a per-day chart."""

    x: float
    y: float
    width: float
    height: float
    day: date
    value: int


@dataclass
class Metric:
    """One counted thing, with its window series and its all-time total."""

    key: str
    label: str
    #: What the number means, in one line — shown under the headline.  A
    #: counter with no definition gets re-interpreted every time it is read.
    definition: str
    total: int
    window_total: int
    #: Same-length lists, oldest day first, with zero-days filled in.  A series
    #: that omits its empty days draws a lie: seven scattered bars look like a
    #: solid week.
    days: list[date] = field(default_factory=list)
    values: list[int] = field(default_factory=list)
    #: Running total *including* everything before the window, so the cumulative
    #: line ends at ``total`` rather than at ``window_total``.
    cumulative: list[int] = field(default_factory=list)
    #: True when the metric is a current state rather than an event stream, so
    #: the template shows the headline and suppresses the charts.
    is_state: bool = False

    @property
    def last_value(self) -> int:
        return self.values[-1] if self.values else 0

    @property
    def peak(self) -> int:
        return max(self.values) if self.values else 0

    @property
    def bars(self) -> list[Bar]:
        """Per-day bars, scaled to the tallest day in the window.

        Scaled to the window peak, not to a shared axis across metrics: these
        series differ by orders of magnitude (searches vs. subscriptions), and
        a shared scale would flatten the small ones to nothing.  Each chart is
        therefore its own axis, which is why the peak is labelled on every one.
        """
        n = len(self.values)
        if not n:
            return []
        slot = CHART_WIDTH / n
        width = max(1.0, slot - BAR_GAP)
        peak = self.peak or 1
        bars: list[Bar] = []
        for i, value in enumerate(self.values):
            # A non-zero day always gets at least 2 units of height, so "one
            # search happened" never renders identically to "none did".
            height = max(2.0, value / peak * CHART_HEIGHT) if value else 0.0
            bars.append(Bar(
                x=i * slot,
                y=CHART_HEIGHT - height,
                width=width,
                height=height,
                day=self.days[i],
                value=value,
            ))
        return bars

    @property
    def cumulative_low(self) -> int:
        """The running total the window opens at — the cumulative chart's floor."""
        if not self.cumulative:
            return 0
        return self.cumulative[0] - (self.values[0] if self.values else 0)

    @property
    def rows(self) -> list[tuple[date, int, int]]:
        """``(day, value, running total)`` triples for the data table.

        Built here because a Django template cannot zip three lists, and the
        table is the non-visual reading of the same numbers the charts draw —
        it must come from the same place or it is a second, drifting dataset.
        """
        return list(zip(self.days, self.values, self.cumulative))

    @property
    def cumulative_path(self) -> str:
        """An SVG ``d`` for the running-total line.

        Baselined at the window's *starting* total rather than at zero: the
        interesting shape is the growth inside the window, and a line that
        starts at the all-time count squashes it against the top of the canvas.
        """
        if not self.cumulative:
            return ""
        n = len(self.cumulative)
        low = self.cumulative[0] - (self.values[0] if self.values else 0)
        high = self.cumulative[-1]
        span = max(1, high - low)
        step = CHART_WIDTH / max(1, n - 1) if n > 1 else CHART_WIDTH
        points = [
            f"{i * step:.2f},{CHART_HEIGHT - (v - low) / span * CHART_HEIGHT:.2f}"
            for i, v in enumerate(self.cumulative)
        ]
        return "M" + " L".join(points)


def _window_days(days: int) -> list[date]:
    """The window's calendar days, oldest first, ending today."""
    today = timezone.localdate()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _daily_counts(
    queryset: QuerySet[Any], field_name: str, window: list[date]
) -> list[int]:
    """Count ``queryset`` rows per day of ``window``, zero-filling gaps."""
    rows = (
        queryset
        .filter(**{f"{field_name}__date__gte": window[0]})
        .annotate(day=TruncDate(field_name))
        .values("day")
        .annotate(n=Count("id"))
    )
    by_day = {row["day"]: row["n"] for row in rows}
    return [by_day.get(day, 0) for day in window]


def _build(
    key: str,
    label: str,
    definition: str,
    queryset: QuerySet[Any],
    field_name: str,
    window: list[date],
) -> Metric:
    """Assemble one event-stream metric from a single queryset."""
    values = _daily_counts(queryset, field_name, window)
    total = queryset.count()
    window_total = sum(values)
    # Walk the running total backwards from the all-time count so the last
    # point equals `total` exactly — deriving it forwards from a "before the
    # window" count needs a second query and can disagree by a row written
    # between the two.
    cumulative: list[int] = []
    running = total - window_total
    for value in values:
        running += value
        cumulative.append(running)
    return Metric(
        key=key,
        label=label,
        definition=definition,
        total=total,
        window_total=window_total,
        days=window,
        values=values,
        cumulative=cumulative,
    )


def _subscription_metric() -> Metric:
    """Active paid subscriptions — a state, so no series.

    dj-stripe keeps subscription status inside the ``stripe_data`` JSON and
    rewrites the row in place on every webhook, so there is no per-day history
    to draw: yesterday's count is simply not recorded anywhere.  The metric
    therefore ships with ``is_state=True`` and the template omits its charts,
    rather than inventing a series from ``created`` timestamps that would count
    cancellations as if they were still active.
    """
    active = Subscription.objects.filter(
        stripe_data__status__in=["active", "trialing"]
    ).count()
    courtesy = User.objects.filter(pro_courtesy=True).count()
    return Metric(
        key="subscriptions",
        label="Paying subscribers",
        definition=(
            "Stripe subscriptions in status active or trialing. "
            f"{courtesy} account{'' if courtesy == 1 else 's'} "
            f"hold{'s' if courtesy == 1 else ''} Pro by courtesy flag and "
            "are not counted here."
        ),
        total=active,
        window_total=active,
        is_state=True,
    )


def collect_metrics(days: int = DEFAULT_WINDOW_DAYS) -> list[Metric]:
    """Every metric on the insights page, in reading order."""
    window = _window_days(days)
    events = EngagementEvent.objects
    return [
        _build(
            "searches_anonymous",
            "Anonymous searches",
            "Searches run by a visitor with no account. The top of the funnel.",
            SearchHistory.objects.filter(user__isnull=True),
            "timestamp",
            window,
        ),
        _build(
            "rate_limit_blocks",
            "Blocked searches",
            "Anonymous visitors who asked for a search after spending the day's one. "
            "The denominator for the wall's conversion rate.",
            events.filter(event_type=EngagementEvent.EventType.RATE_LIMIT_BLOCK),
            "timestamp",
            window,
        ),
        _build(
            "locked_views",
            "Locked-content hits",
            "A free-tier reader met an edition their plan does not cover.",
            events.filter(event_type=EngagementEvent.EventType.LOCKED_CONTENT_VIEW),
            "timestamp",
            window,
        ),
        _build(
            "signups",
            "Signups",
            "Accounts created. The wall's numerator.",
            User.objects.all(),
            "date_joined",
            window,
        ),
        _build(
            "edition_requests",
            "Edition requests",
            "Visitors who told us which code or edition they need. Demand for "
            "what we do not carry yet.",
            EditionRequest.objects.all(),
            "created_at",
            window,
        ),
        _subscription_metric(),
        _build(
            "searches_signed_in",
            "Signed-in searches",
            "Searches by an account holder. Usage, not acquisition — this is the "
            "number that says whether anyone comes back.",
            SearchHistory.objects.filter(user__isnull=False),
            "timestamp",
            window,
        ),
        _build(
            "logins",
            "Logins",
            "Successful sign-ins. Returning readers, counted per session rather "
            "than per search.",
            AuthEvent.objects.filter(event_type=AuthEvent.EventType.LOGIN),
            "timestamp",
            window,
        ),
    ]


def conversion_rates(metrics: list[Metric]) -> list[dict[str, Any]]:
    """The two ratios worth watching, as whole percentages.

    Reported all-time rather than per-window: at current volume a 90-day window
    can hold a single-digit denominator, and a rate computed on four blocks
    swings 25 points on one signup.  The window charts show the trend; these
    show the level.
    """
    by_key = {m.key: m for m in metrics}

    def ratio(numerator: str, denominator: str) -> int | None:
        low = by_key[denominator].total
        return round(by_key[numerator].total / low * 100) if low else None

    return [
        {
            "label": "Signup per blocked search",
            "value": ratio("signups", "rate_limit_blocks"),
            "definition": "Signups ÷ blocked searches, all time. Measures the wall's copy.",
        },
        {
            "label": "Paid per signup",
            "value": ratio("subscriptions", "signups"),
            "definition": "Active subscriptions ÷ accounts, all time. "
                          "Measures whether the gated editions are worth paying for.",
        },
    ]


def edition_requests(limit: int = 25, days: int = DEFAULT_WINDOW_DAYS) -> list[dict[str, Any]]:
    """What visitors asked us to carry, newest first.

    Shown as rows rather than as counts because the text is free-form: "NBC
    2015", "the 1990 OBC" and "Alberta" are three different asks that no
    grouping key would combine correctly, and reading twenty of them is how
    the pattern actually becomes visible.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (
        EditionRequest.objects
        .filter(created_at__gte=since)
        .order_by("-created_at")[:limit]
    )
    return [
        {
            "code_text": row.code_text,
            "email": row.email,
            # Read from the choices map rather than get_FOO_display() so
            # Pyright (no Django plugin) can see the attribute exists.
            "surface": dict(EditionRequest.Surface.choices).get(
                row.surface, row.surface
            ),
            "created_at": row.created_at,
        }
        for row in rows
    ]


def top_queries(limit: int = 15, days: int = DEFAULT_WINDOW_DAYS) -> list[dict[str, Any]]:
    """The most-repeated search text in the window.

    Not a vanity number: this is free keyword research from real visitors, and
    it is the shortest path from "someone searched for X" to a page that ranks
    for X.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (
        SearchHistory.objects
        .filter(timestamp__gte=since)
        .values("query")
        .annotate(n=Count("id"))
        .order_by("-n", "query")[:limit]
    )
    return [{"query": row["query"], "count": row["n"]} for row in rows]
