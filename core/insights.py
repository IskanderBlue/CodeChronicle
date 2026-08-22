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
from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import (
    Case,
    Count,
    F,
    IntegerField,
    Q,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, TruncDate
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from djstripe.models import Subscription

from config.exports import EXPORT_KINDS
from core.models import (
    AuthEvent,
    BackupRun,
    CodeEditionProvisionVersion,
    EditionRequest,
    EngagementEvent,
    ProvisionFeedback,
    ProvisionFetch,
    Regulation,
    SearchHistory,
    User,
)

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
CHART_BAR_GAP = 2


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
        width = max(1.0, slot - CHART_BAR_GAP)
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
            "comparisons",
            "Comparisons",
            "Readers who opened two versions side by side. The question the "
            "product exists to answer, and the one two browser tabs cannot.",
            events.filter(event_type=EngagementEvent.EventType.VERSION_COMPARISON),
            "timestamp",
            window,
        ),
        _build(
            "comparisons_cross_edition",
            "Cross-edition comparisons",
            "Comparisons spanning two editions. Pro is needed on at least one "
            "side, so this is the value the price buys.",
            events.filter(
                event_type=EngagementEvent.EventType.VERSION_COMPARISON,
                context__cross_edition=True,
            ),
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
        _build(
            "feedback_reports",
            "Reader reports",
            "Readers who told us a text on the site looks wrong. Free verification, "
            "and the clearest sign that somebody read closely enough to argue.",
            ProvisionFeedback.objects.all(),
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


def _feedback_target_url(row: ProvisionFeedback) -> str:
    """A link back to what the reader was looking at, or "".

    Built from the stored natural key rather than from a saved URL string: the
    permalink shape is allowed to change, and a report filed last year should
    still open the right page after it does.  Returns "" rather than raising —
    a report whose edition has since been unloaded is still a report worth
    reading, and the queue must not 500 over a dead link.
    """
    if row.reg_id:
        # Regulation pages are addressed by row pk, and pk is exactly what a
        # reload replaces, so resolve the number to a row at read time.
        # code_name is a property, not a column, hence the Python-side match.
        for regulation in Regulation.objects.filter(
            reg_id=row.reg_id
        ).select_related("edition", "edition__code"):
            if regulation.edition.code_name == row.code_edition:
                return reverse("core:regulation_detail", args=[regulation.pk])
        return ""
    if row.version is None or not row.provision_id:
        return ""
    try:
        if row.division:
            return reverse(
                "core:provision_permalink",
                args=[row.code_edition, row.division, row.provision_id, row.version],
            )
        return reverse(
            "core:provision_permalink_no_division",
            args=[row.code_edition, row.provision_id, row.version],
        )
    except NoReverseMatch:
        return ""


def _feedback_dict(row: ProvisionFeedback) -> dict[str, Any]:
    """One queue row, shaped for the template."""
    return {
        "id": row.pk,
        "note": row.note,
        "email": row.email,
        "target_ref": row.target_ref,
        "target_url": _feedback_target_url(row),
        "status": row.status,
        # Read from the choices map rather than get_FOO_display() so Pyright
        # (no Django plugin) can see the attribute exists.
        "status_label": dict(ProvisionFeedback.Status.choices).get(
            row.status, row.status
        ),
        "surface": dict(ProvisionFeedback.Surface.choices).get(
            row.surface, row.surface
        ),
        "created_at": row.created_at,
    }


def feedback_row(pk: int) -> dict[str, Any] | None:
    """One queue row by pk, for the status control's partial re-render."""
    row = ProvisionFeedback.objects.filter(pk=pk).first()
    return _feedback_dict(row) if row is not None else None


def feedback_reports(limit: int = 50, days: int = DEFAULT_WINDOW_DAYS) -> list[dict[str, Any]]:
    """Reader reports, untriaged first and newest first within that.

    Ordered by state before date on purpose.  The question this queue answers
    is "what have I not decided about yet", and a strict date order buries a
    week-old untriaged report under yesterday's resolved ones.

    Windowed like the other sections, with one exception: a report still in
    ``new`` is always listed, however old.  An unanswered report does not stop
    being unanswered because 90 days passed — that is precisely when it most
    needs to be visible.
    """
    since = timezone.now() - timedelta(days=days)
    rows = (
        ProvisionFeedback.objects
        .filter(Q(created_at__gte=since) | Q(status=ProvisionFeedback.Status.NEW))
        .order_by(
            # Postgres sorts by the stored value, and "new" happens to sort
            # after "fixed" alphabetically, so order on a computed flag rather
            # than on the column.
            Case(
                When(status=ProvisionFeedback.Status.NEW, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            "-created_at",
        )[:limit]
    )
    return [_feedback_dict(row) for row in rows]


def export_counts(days: int = DEFAULT_WINDOW_DAYS) -> list[dict[str, Any]]:
    """How often each export was taken, in the window and all time.

    The reason all four exports shipped at once.  We could not guess which one
    a code consultant reaches for, and asking produces an opinion rather than
    a measurement — so this table is the measurement, and after sixty days an
    export nobody used is removed rather than defended.

    A kind with no rows still gets a row here, reading zero.  A missing line
    would be read as "not built yet", which is the opposite of the finding.

    The citation kinds are broken out by format for the same reason: a factum
    and a report body take different strings, and one of the two may turn out
    to be nobody's.
    """
    since = timezone.now() - timedelta(days=days)
    events = EngagementEvent.objects.filter(
        event_type=EngagementEvent.EventType.EXPORT
    )
    rows: list[dict[str, Any]] = []
    for kind, label, description in EXPORT_KINDS:
        of_kind = events.filter(context__kind=kind)
        row: dict[str, Any] = {
            "kind": kind,
            "label": label,
            "description": description,
            "window": of_kind.filter(timestamp__gte=since).count(),
            "total": of_kind.count(),
            "formats": [],
        }
        if kind == "citation":
            row["formats"] = [
                {
                    "format": fmt,
                    "window": of_kind.filter(
                        context__format=fmt, timestamp__gte=since
                    ).count(),
                    "total": of_kind.filter(context__format=fmt).count(),
                }
                for fmt in ("legal", "report", "reference")
            ]
        rows.append(row)
    return rows


#: How old the newest good off-host backup may be before the panel calls it
#: stale.  The schedule is daily, so 26 hours allows one late run — a deploy
#: replacing the container while the timer fires costs a day — without letting
#: two consecutive misses pass as healthy.
BACKUP_STALE_AFTER_HOURS = 26


def backup_state() -> dict[str, Any]:
    """When the off-host backup last worked, and whether that is recent enough.

    This is the record, not the alarm.  Nobody watches a dashboard at 07:00, so
    the alarm is the dead-man's switch that pings from the backup host.  What
    this answers is the question you have *after* something goes wrong: when did
    it last work, how big was it, and what did the failure say.

    Age is measured from the newest **succeeded upload**.  Three exclusions,
    each of which would otherwise let the panel read healthy while no off-host
    copy exists:

    * a failed run is not a backup, however recent its row;
    * a ``--dest`` drill uploads nothing, so a run of drills must not refresh
      the clock;
    * an empty table reads as stale, not as unknown — a backup that has never
      run and a backup whose history was lost are the same situation.
    """
    uploads = BackupRun.objects.filter(kind=BackupRun.Kind.UPLOAD)
    newest_good = uploads.filter(succeeded=True).order_by("-started_at").first()
    newest_any = BackupRun.objects.order_by("-started_at").first()

    age_hours: float | None = None
    if newest_good and newest_good.finished_at:
        delta = timezone.now() - newest_good.finished_at
        age_hours = delta.total_seconds() / 3600

    return {
        "last_good": newest_good,
        # Shown only when it is not the same row, so a healthy panel does not
        # carry a second timestamp that reads like a second backup.
        "last_attempt": newest_any if newest_any != newest_good else None,
        "age_hours": age_hours,
        "stale_after_hours": BACKUP_STALE_AFTER_HOURS,
        "is_stale": age_hours is None or age_hours > BACKUP_STALE_AFTER_HOURS,
        "failures_recent": uploads.filter(succeeded=False).count(),
    }


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


def ledger_health(days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:
    """Whether the reading ledger is still recording, from a second record.

    ``core.reading_ledger.record_reads`` swallows every failure, because a
    ledger write must never break a read.  That is correct and it creates this
    problem: a ledger which stopped writing looks exactly like an account which
    stopped reading, and the code best placed to report the failure is the code
    that is failing.  A counter written by the failing function is not evidence.

    So this compares two records of the same event, written by two functions.
    ``EngagementEvent`` records a ``PROVISION_VERSION_VIEW`` when a signed-in
    reader opens a provision; ``ProvisionFetch`` records the texts that page
    delivered.  A day with the first and none of the second is the alarm.

    Three readings, and they answer different questions:

    * Both counts fall to zero — the readers stopped.  Nothing is broken.
    * Views continue and ledger writes stop — the ledger broke.
    * ``last_write`` is old while ``last_view`` is recent — the same failure,
      visible without waiting for a whole day to close.
    """
    since = timezone.now() - timedelta(days=days)

    view_days = {
        row["day"]
        for row in EngagementEvent.objects
        .filter(
            event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW,
            user__isnull=False,
            timestamp__gte=since,
        )
        .annotate(day=TruncDate("timestamp"))
        .values("day")
        .distinct()
    }
    ledger_days = {
        row["day"]
        for row in ProvisionFetch.objects
        .filter(last_fetched_at__gte=since)
        .annotate(day=TruncDate("last_fetched_at"))
        .values("day")
        .distinct()
    }

    # A page that delivers forty texts and records three is not a silent day,
    # so the day-level test above passes it.  The three bulk surfaces stamp
    # what they handed over beside what reached the ledger, and a request where
    # the second is lower is a partial failure — the one thing days cannot see.
    #
    # ``->>`` then a cast, rather than comparing the JSON values directly: a
    # jsonb comparison would order 9 after 10, and this is a "fewer than"
    # question.  A row missing the keys yields NULL and drops out, which is
    # what should happen to a surface that does not report.
    #
    # Signed-in readers only, like everything else here.  ``record_reads``
    # returns 0 for an anonymous reader by design, so counting those would
    # report every anonymous read as a total ledger failure.
    shortfalls = (
        EngagementEvent.objects
        .filter(
            timestamp__gte=since,
            user__isnull=False,
            context__has_key="delivered",
        )
        .annotate(
            n_delivered=Cast(
                KeyTextTransform("delivered", "context"), IntegerField()
            ),
            n_recorded=Cast(
                KeyTextTransform("recorded", "context"), IntegerField()
            ),
        )
        .filter(n_recorded__lt=F("n_delivered"))
    )

    silent = sorted(view_days - ledger_days)
    return {
        "days_with_views": len(view_days),
        "days_with_ledger": len(ledger_days),
        # Requests that delivered more text than they recorded.  Any number
        # above zero is a bug: the two counts describe one response.
        "shortfall_requests": shortfalls.count(),
        "last_shortfall": (
            shortfalls.order_by("-timestamp")
            .values_list("timestamp", flat=True)
            .first()
        ),
        # Days a signed-in reader opened a provision and nothing reached the
        # ledger.  One is worth looking at; a run of them is a broken ledger.
        "silent_days": len(silent),
        "last_silent_day": silent[-1] if silent else None,
        "last_view": (
            EngagementEvent.objects
            .filter(
                event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW,
                user__isnull=False,
            )
            .order_by("-timestamp")
            .values_list("timestamp", flat=True)
            .first()
        ),
        "last_write": (
            ProvisionFetch.objects
            .order_by("-last_fetched_at")
            .values_list("last_fetched_at", flat=True)
            .first()
        ),
    }


#: How long a pause ends a sitting.  A reader who comes back after lunch has
#: started a second one; a reader turning pages has not.
SITTING_GAP = timedelta(minutes=30)


def _sittings_in_window(since: datetime) -> dict[str, int]:
    """Per account, how many separate sittings acquired new text.

    Derived from ``first_fetched_at`` rather than stored, and that is the point.
    The obvious column — a run id minted per session — measures the *session*,
    and ``SESSION_COOKIE_AGE`` is two weeks here, so a consultant who stays
    signed in reads a fortnight under one id and scores the single run that is
    supposed to be the recorder's signature.  A gap in the timestamps is the
    real thing being asked about, it needs no migration, and ``SITTING_GAP``
    can be re-tuned against data already collected.

    Only first sightings count, because a sitting here means "when did this
    account acquire text", and re-reading something it already holds acquires
    nothing.
    """
    stamps: dict[str, list[datetime]] = {}
    for email, at in (
        ProvisionFetch.objects
        .filter(first_fetched_at__gte=since)
        .order_by("user__email", "first_fetched_at")
        .values_list("user__email", "first_fetched_at")
    ):
        stamps.setdefault(email, []).append(at)

    counts: dict[str, int] = {}
    for email, times in stamps.items():
        sittings = 1
        for before, after in zip(times, times[1:], strict=False):
            if after - before > SITTING_GAP:
                sittings += 1
        counts[email] = sittings
    return counts


def _cold_arrivals_in_window(since: datetime) -> dict[str, int]:
    """Per account: how many page views arrived with no ``Referer``.

    The question the reading ledger cannot answer.  A reader follows links; a
    script composes URLs.  ``core.events.arrival_context`` classifies the
    referrer without storing it, so this counts walks and not reading lists.

    A shape, not a quantity.  It has no threshold and nothing acts on it — a
    person reads it, and the remedy is the Terms and the revoke.
    """
    rows = (
        EngagementEvent.objects
        .filter(
            timestamp__gte=since,
            user__isnull=False,
            event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW,
            context__arrival="cold",
        )
        .values("user__email")
        .annotate(cold=Count("id"))
    )
    return {row["user__email"]: row["cold"] for row in rows}


def reading_coverage(days: int = DEFAULT_WINDOW_DAYS) -> list[dict[str, Any]]:
    """Per account: how much of the corpus it has taken, and how much is new.

    The question this answers is "is anybody recording the corpus", and the
    reason it is shaped this way is that **volume cannot answer it**.  A busy
    subscriber and a bulk copy are the same order of magnitude, because the
    corpus is small.  Novelty separates them cleanly:

    - Somebody recording almost never fetches the same provision twice, so
      ``new_share`` sits near 100% and ``coverage`` climbs in a straight line.
    - A consultant returns to the provisions their practice turns on, so most
      fetches are repeats, ``new_share`` falls away, and ``coverage`` flattens
      out in the low single digits.

    ``coverage`` is measured against every version this product holds, not
    against the window, because what matters is the share of the whole an
    account has accumulated — a copy made a month at a time is still a copy.
    The denominator counts **versions that carry text**, because the ledger
    only records those: every division, part, section and subsection has an
    empty body, and counting headings on one side of the fraction and not the
    other understates every account.

    **Read ``coverage`` for the website and ``new_share`` for the API.**  An
    API caller asks for one text at a time, so novelty measures a decision.
    A website page used to hand over up to forty texts the reader never asked
    for individually, which made its novelty an artefact of page size.  A
    signed-in reader's page now fetches each body separately
    (``core.views.regulation.provision_text``), so ``web_held`` is closing on
    the same meaning — but rows written before that landed are not, and
    ``web_held`` and ``api_held`` stay apart for the same underlying reason:
    one curve over both is a curve over a population that does not exist.

    ``cold`` measures **shape** rather than quantity, and shape has no ceiling
    problem: a reader follows links, a script composes URLs.

    A report to read, never a limit.  Nothing acts on these numbers; a person
    does, and the remedy is the Terms and the revoke.
    """
    since = timezone.now() - timedelta(days=days)
    corpus = (
        CodeEditionProvisionVersion.objects
        .exclude(html="")
        .exclude(html__isnull=True)
        .count()
    )

    rows = (
        ProvisionFetch.objects
        .filter(last_fetched_at__gte=since)
        .values("user__email")
        .annotate(
            held=Count("id"),
            fetches=Sum("fetch_count"),
            new_in_window=Count("id", filter=Q(first_fetched_at__gte=since)),
            web_held=Count("id", filter=Q(source=ProvisionFetch.Source.WEB)),
            api_held=Count("id", filter=Q(source=ProvisionFetch.Source.API)),
        )
        .order_by("-new_in_window", "-held")
    )

    sittings = _sittings_in_window(since)
    cold = _cold_arrivals_in_window(since)

    out: list[dict[str, Any]] = []
    for row in rows:
        fetches = row["fetches"] or 0
        out.append({
            "email": row["user__email"],
            # Distinct provision texts this account holds, in total.
            "held": row["held"],
            # Requests it made in the window, repeats included.
            "fetches": fetches,
            "new_in_window": row["new_in_window"],
            # Of what it fetched in the window, how much it had never seen.
            # Near 100 is the recorder's signature; a working reader is low.
            # Only meaningful for the API side — see the docstring.
            "new_share": round(100 * row["new_in_window"] / fetches) if fetches else 0,
            # Which surface delivered it.  Reported apart because the two are
            # read with different measures, not to be added back together.
            "web_held": row["web_held"],
            "api_held": row["api_held"],
            # How many separate sittings acquired those texts.  The whole
            # corpus in one sitting and the same texts across a year are
            # different facts that ``held`` alone cannot tell apart.
            "sittings": sittings.get(row["user__email"], 0),
            # Share of the whole corpus this account now holds.
            "coverage": round(100 * row["held"] / corpus, 1) if corpus else 0.0,
            # Shape, not quantity: many cold arrivals is composed URLs rather
            # than followed links.  See ``_cold_arrivals_in_window``.
            "cold": cold.get(row["user__email"], 0),
        })
    return out
