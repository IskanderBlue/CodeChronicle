"""Tests for the staff insights dashboard and the metrics behind it.

The load-bearing property is that the headline total, the bars, and the
cumulative line all describe the same rows: a dashboard that disagrees with
itself is worse than none, because it is read for decisions rather than
audited.  Most of these tests assert exactly that agreement.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.insights import (
    CHART_HEIGHT,
    collect_metrics,
    conversion_rates,
    top_queries,
)
from core.models import EngagementEvent, SearchHistory, User


def _metric(metrics, key):
    return next(m for m in metrics if m.key == key)


@pytest.fixture
def searches(db):
    """Three anonymous searches today, one 5 days ago, one 200 days ago."""
    now = timezone.now()
    made = []
    for offset in (0, 0, 0, 5, 200):
        row = SearchHistory.objects.create(
            ip_address="203.0.113.9", query=f"q{offset}", result_count=1
        )
        # auto_now_add ignores an assigned value, so the timestamp is pushed
        # back with an update() after the insert.
        SearchHistory.objects.filter(pk=row.pk).update(
            timestamp=now - timedelta(days=offset)
        )
        made.append(row)
    return made


@pytest.mark.django_db
class TestCollectMetrics:
    def test_totals_count_every_row_including_outside_the_window(self, searches):
        metric = _metric(collect_metrics(days=30), "searches_anonymous")
        assert metric.total == 5
        assert metric.window_total == 4  # the 200-day-old row falls outside

    def test_series_is_zero_filled_to_the_window_length(self, searches):
        metric = _metric(collect_metrics(days=30), "searches_anonymous")
        assert len(metric.days) == 30
        assert len(metric.values) == 30
        assert len(metric.cumulative) == 30
        assert metric.values[-1] == 3  # today
        assert metric.values[-6] == 1  # five days ago

    def test_cumulative_ends_at_the_all_time_total(self, searches):
        """The running line and the headline number must agree at the right edge."""
        metric = _metric(collect_metrics(days=30), "searches_anonymous")
        assert metric.cumulative[-1] == metric.total

    def test_bars_span_the_canvas_and_scale_to_the_peak(self, searches):
        metric = _metric(collect_metrics(days=30), "searches_anonymous")
        bars = metric.bars
        assert len(bars) == 30
        tallest = max(bars, key=lambda b: b.height)
        assert tallest.value == metric.peak
        assert tallest.height == pytest.approx(CHART_HEIGHT)
        # A zero day draws nothing; a non-zero day always draws something.
        assert all(b.height == 0 for b in bars if b.value == 0)
        assert all(b.height >= 2 for b in bars if b.value)

    def test_empty_metric_draws_an_empty_axis_not_nothing(self, db):
        """Zero everywhere is a real answer and must render as a flat baseline.

        The window still yields one bar per day, all of zero height, so the
        chart keeps its axis and its date labels — a card that collapses to
        blank reads as broken rather than as "nothing happened".
        """
        metric = _metric(collect_metrics(days=30), "signups")
        assert metric.total == 0
        assert metric.peak == 0
        assert len(metric.bars) == 30
        assert all(bar.height == 0 for bar in metric.bars)
        assert metric.cumulative == [0] * 30

    def test_a_metric_with_no_window_has_no_bars(self, db):
        """The degenerate guard: no days, no geometry, no division by zero."""
        metric = _metric(collect_metrics(days=30), "subscriptions")
        assert metric.bars == []
        assert metric.cumulative_path == ""

    def test_rows_pair_each_day_with_its_value_and_running_total(self, searches):
        metric = _metric(collect_metrics(days=30), "searches_anonymous")
        rows = metric.rows
        assert len(rows) == 30
        assert [r[1] for r in rows] == metric.values
        assert rows[-1][2] == metric.total

    def test_subscriptions_is_a_state_with_no_series(self, db):
        metric = _metric(collect_metrics(days=30), "subscriptions")
        assert metric.is_state is True
        assert metric.values == []


@pytest.mark.django_db
class TestRateLimitBlockCapture:
    """The middleware must leave a row, or the block is invisible to the page."""

    def test_a_teaser_band_search_records_an_event(self, client, settings):
        """The teaser still counts as a block: the reader asked and we withheld."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 10
        SearchHistory.objects.create(
            ip_address="203.0.113.9", query="first", result_count=0
        )
        response = client.post(
            "/search-results/", {"query": "second"}, REMOTE_ADDR="203.0.113.9"
        )
        # The search runs, so the page renders — the text is what is withheld.
        assert response.status_code == 200
        blocks = EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.RATE_LIMIT_BLOCK
        )
        assert blocks.count() == 1
        block = blocks.first()
        assert block is not None
        assert block.context["band"] == "teaser"
        assert _metric(collect_metrics(days=30), "rate_limit_blocks").total == 1

    def test_a_hard_band_search_is_refused(self, client, settings):
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 2
        for text in ("first", "second"):
            SearchHistory.objects.create(
                ip_address="203.0.113.9", query=text, result_count=0
            )
        response = client.post(
            "/search-results/", {"query": "third"}, REMOTE_ADDR="203.0.113.9"
        )
        assert response.status_code == 429
        assert _metric(collect_metrics(days=30), "rate_limit_blocks").total == 1


@pytest.mark.django_db
class TestConversionRates:
    def test_rate_is_none_when_the_denominator_is_empty(self, db):
        rates = conversion_rates(collect_metrics(days=30))
        assert all(r["value"] is None for r in rates)

    def test_signup_per_block_is_a_whole_percentage(self, db):
        for _ in range(4):
            EngagementEvent.objects.create(
                ip_address="203.0.113.9",
                event_type=EngagementEvent.EventType.RATE_LIMIT_BLOCK,
            )
        User.objects.create_user(email="a@example.com", password="x")
        rates = conversion_rates(collect_metrics(days=30))
        assert rates[0]["value"] == 25


@pytest.mark.django_db
class TestTopQueries:
    def test_repeated_text_is_grouped_and_ordered_by_count(self, db):
        for query in ("fire", "fire", "stairs"):
            SearchHistory.objects.create(
                ip_address="203.0.113.9", query=query, result_count=0
            )
        rows = top_queries(days=30)
        assert rows[0] == {"query": "fire", "count": 2}
        assert rows[1] == {"query": "stairs", "count": 1}


@pytest.mark.django_db
class TestInsightsView:
    def test_anonymous_is_redirected_to_login(self, client):
        response = client.get(reverse("core:insights"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_signed_in_non_staff_is_redirected(self, client):
        user = User.objects.create_user(email="reader@example.com", password="x")
        client.force_login(user)
        response = client.get(reverse("core:insights"))
        assert response.status_code == 302

    def test_staff_sees_the_dashboard(self, client, searches):
        user = User.objects.create_user(email="staff@example.com", password="x")
        user.is_staff = True
        user.save()
        client.force_login(user)
        response = client.get(reverse("core:insights"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "Anonymous searches" in body
        assert "<rect" in body

    def test_window_falls_back_to_the_default_for_an_unoffered_value(self, client):
        user = User.objects.create_user(email="staff2@example.com", password="x")
        user.is_staff = True
        user.save()
        client.force_login(user)
        for raw in ("7", "abc", ""):
            response = client.get(reverse("core:insights"), {"days": raw})
            assert response.context["days"] == 90
        response = client.get(reverse("core:insights"), {"days": "30"})
        assert response.context["days"] == 30
