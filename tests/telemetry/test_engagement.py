"""Tests for engagement / click tracking (EngagementEvent)."""

import json
from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    Regulation,
    SearchHistory,
)


def _build_provision() -> dict:
    """A division-less OBC 1997 provision with one in-force version."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6),
    )
    provision = CodeEditionProvision.objects.create(
        edition=edition, provision_id="1.1.1.1.", level="article", division="",
    )
    version = CodeEditionProvisionVersion.objects.create(
        provision=provision, version=0,
        effective_date=date(1998, 4, 6), title="Application",
        html="<p>This Code applies to all buildings.</p>",
    )
    return {"code": code, "edition": edition, "provision": provision, "version": version}


@pytest.fixture
def locked_fixtures(db, settings):
    """The same provision with the free window left at its default (OBC 2006),
    so the fixture edition is *outside* it — the locked case.

    Pinned explicitly rather than inherited from settings so the locked tests
    keep testing refusal even if the product's free window widens later.
    """
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
    return _build_provision()


@pytest.fixture
def provision_fixtures(db, settings):
    """A division-less OBC 1997 provision with one in-force version.

    The fixture edition is placed *in* the free tier for the duration of the
    test.  Engagement capture is orthogonal to the content gate (``accounts.access``,
    now unconditional), and without this the anonymous client these tests use
    would be refused at the gate before any capture site ran — a 403 on the
    permalink/regulation views, and a locked teaser (200, no event) on the
    viewer partial.  Overriding the free window rather than switching the
    fixture to whichever edition happens to be free today keeps these tests
    independent of the product's tier scoping.
    """
    settings.FREE_TIER_CODE_NAMES = ["OBC_1997"]
    return _build_provision()


@pytest.mark.django_db
class TestProvisionPermalinkTracking:
    def test_records_provision_version_view(self, client: Client, provision_fixtures):
        version = provision_fixtures["version"]
        url = reverse(
            "web:provision_permalink_no_division",
            kwargs={"code_edition": "OBC_1997", "provision_id": "1.1.1.1.", "version": 0},
        )
        response = client.get(url)
        assert response.status_code == 200

        events = list(EngagementEvent.objects.all())
        assert len(events) == 1
        event = events[0]
        assert event.event_type == EngagementEvent.EventType.PROVISION_VERSION_VIEW
        assert event.object_type == "CodeEditionProvisionVersion"
        assert event.object_id == version.pk
        assert event.context["provision_id"] == "1.1.1.1."
        assert event.context["surface"] == "permalink"


@pytest.mark.django_db
class TestRegulationDetailTracking:
    def test_records_regulation_view(self, client: Client, provision_fixtures):
        reg = Regulation.objects.create(
            reg_id="403/97", edition=provision_fixtures["edition"], role="base",
            effective_date=date(1998, 4, 6),
        )
        response = client.get(f"/regulation/{reg.pk}/")
        assert response.status_code == 200

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.REGULATION_VIEW
        assert event.object_type == "Regulation"
        assert event.object_id == reg.pk
        assert event.context["reg_id"] == "403/97"

    def test_tracking_failure_is_non_fatal(
        self, client: Client, provision_fixtures, monkeypatch
    ):
        reg = Regulation.objects.create(
            reg_id="403/97", edition=provision_fixtures["edition"], role="base",
            effective_date=date(1998, 4, 6),
        )

        def _boom(*args, **kwargs):
            raise RuntimeError("db is on fire")

        monkeypatch.setattr(EngagementEvent.objects, "create", _boom)

        # The page must still render even though the event write blows up.
        response = client.get(f"/regulation/{reg.pk}/")
        assert response.status_code == 200
        assert "403/97" in response.content.decode()


@pytest.mark.django_db
class TestViewerSectionTracking:
    def test_records_view_attributed_to_search(self, client: Client, provision_fixtures):
        version = provision_fixtures["version"]
        search = SearchHistory.objects.create(
            query="application of the code", parsed_params={}, result_count=1,
        )
        url = reverse("web:viewer_section_content")
        response = client.get(url, {
            "code": "OBC",
            "edition_id": "1997",
            "division": "",
            "provision_id": "1.1.1.1.",
            "query_date": "2020-01-01",
            "search_id": str(search.pk),
        }, HTTP_HX_REQUEST="true")
        assert response.status_code == 200

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.PROVISION_VERSION_VIEW
        assert event.object_id == version.pk
        assert event.search_id == search.pk
        assert event.context["surface"] == "search_viewer"

    def test_bad_search_id_is_dropped_not_fatal(self, client: Client, provision_fixtures):
        url = reverse("web:viewer_section_content")
        response = client.get(url, {
            "code": "OBC", "edition_id": "1997", "division": "",
            "provision_id": "1.1.1.1.", "query_date": "2020-01-01",
            "search_id": "not-a-number",
        }, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        event = EngagementEvent.objects.get()
        assert event.search_id is None

    def test_non_htmx_get_is_not_counted(self, client: Client, provision_fixtures):
        # A plain GET (crawler / link prefetch / refreshed URL) has no
        # HX-Request header and must not inflate the click-through metric —
        # only genuine htmx drill-ins are recorded.
        url = reverse("web:viewer_section_content")
        response = client.get(url, {
            "code": "OBC", "edition_id": "1997", "division": "",
            "provision_id": "1.1.1.1.", "query_date": "2020-01-01",
        })
        assert response.status_code == 200
        assert not EngagementEvent.objects.exists()


@pytest.mark.django_db
class TestBeaconEndpoint:
    def test_records_result_link_click_with_search_link(self, client: Client):
        search = SearchHistory.objects.create(
            query="fire safety", parsed_params={}, result_count=3,
        )
        response = client.post(
            "/api/event",
            data=json.dumps({
                "event_type": "result_link_click",
                "object_type": "CodeEditionProvisionVersion",
                "object_id": 42,
                "search_id": search.pk,
                "context": {"surface": "source_link"},
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.RESULT_LINK_CLICK
        assert event.object_id == 42
        assert event.search_id == search.pk

    def test_records_results_expand_view(self, client: Client):
        # The inline result-expand fires this via window.ccRecordView — a
        # provision_version_view with no version pk (object_id null), the
        # provision identified in context, attributed to the search.
        search = SearchHistory.objects.create(
            query="guards and handrails", parsed_params={}, result_count=5,
        )
        response = client.post(
            "/api/event",
            data=json.dumps({
                "event_type": "provision_version_view",
                "object_type": "CodeEditionProvision",
                "search_id": search.pk,
                "context": {
                    "surface": "results_expand",
                    "code": "OBC_2012",
                    "provision_id": "3.4.6.1.",
                    "division": "B",
                },
            }),
            content_type="application/json",
        )
        assert response.status_code == 200

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.PROVISION_VERSION_VIEW
        assert event.object_id is None
        assert event.search_id == search.pk
        assert event.context["surface"] == "results_expand"
        assert event.context["provision_id"] == "3.4.6.1."

    def test_rejects_unknown_event_type(self, client: Client):
        response = client.post(
            "/api/event",
            data=json.dumps({"event_type": "mining_bitcoin"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        assert EngagementEvent.objects.count() == 0

    def test_not_rate_limited(self, client: Client, settings):
        # Exhaust the anonymous daily search budget for this IP, then confirm
        # the beacon still records — it executes no search, so the rate-limit
        # middleware (which only guards /search-results/) must not block it.
        settings.RATE_LIMIT_ANONYMOUS = 1
        SearchHistory.objects.create(
            ip_address="127.0.0.1", query="x", parsed_params={}, result_count=0,
        )
        response = client.post(
            "/api/event",
            data=json.dumps({"event_type": "result_link_click"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.RESULT_LINK_CLICK
        ).exists()


@pytest.mark.django_db
class TestLockedContentTracking:
    """Every other event type records value delivered; this one records value
    withheld — a free user meeting the content gate.

    The fixtures here deliberately do NOT widen the free tier: an OBC 1997
    edition with the default free window (OBC 2006) is exactly the locked case.
    """

    def test_permalink_refusal_is_recorded(self, client: Client, locked_fixtures):
        url = reverse(
            "web:provision_permalink_no_division",
            kwargs={"code_edition": "OBC_1997", "provision_id": "1.1.1.1.", "version": 0},
        )
        response = client.get(url)
        assert response.status_code == 403

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.LOCKED_CONTENT_VIEW
        assert event.context["surface"] == "permalink"
        assert event.context["code_edition"] == "OBC_1997"

    def test_regulation_detail_refusal_is_recorded(self, client: Client, locked_fixtures):
        reg = Regulation.objects.create(
            reg_id="403/97", edition=locked_fixtures["edition"], role="base",
            effective_date=date(1998, 4, 6),
        )
        response = client.get(f"/regulation/{reg.pk}/")
        assert response.status_code == 403

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.LOCKED_CONTENT_VIEW
        assert event.context["surface"] == "regulation_detail"

    def test_refusal_attributes_to_the_originating_search(
        self, client: Client, locked_fixtures
    ):
        # decorateResultLinks() appends ?search_id= to in-app result links, so a
        # refusal reached from a result set can be joined back to the query that
        # produced it — the join that makes this a conversion signal.
        search = SearchHistory.objects.create(
            query="fire separation", parsed_params={}, result_count=0,
        )
        url = reverse(
            "web:provision_permalink_no_division",
            kwargs={"code_edition": "OBC_1997", "provision_id": "1.1.1.1.", "version": 0},
        )
        client.get(url, {"search_id": str(search.pk)})
        assert EngagementEvent.objects.get().search_id == search.pk

    def test_viewer_drill_in_refusal_is_recorded(self, client: Client, locked_fixtures):
        url = reverse("web:viewer_section_content")
        response = client.get(url, {
            "code": "OBC", "edition_id": "1997", "division": "",
            "provision_id": "1.1.1.1.", "query_date": "2020-01-01",
        }, HTTP_HX_REQUEST="true")
        assert response.status_code == 200

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.LOCKED_CONTENT_VIEW
        assert event.context["surface"] == "search_viewer"
        assert event.context["provision_id"] == "1.1.1.1."

    def test_non_htmx_viewer_refusal_is_not_counted(self, client: Client, locked_fixtures):
        # Same rule as the view capture: a crawler or refreshed URL is not a
        # user meeting the paywall, and must not inflate the signal.
        url = reverse("web:viewer_section_content")
        client.get(url, {
            "code": "OBC", "edition_id": "1997", "division": "",
            "provision_id": "1.1.1.1.", "query_date": "2020-01-01",
        })
        assert not EngagementEvent.objects.exists()

    def test_search_returning_locked_results_records_an_impression(
        self, client: Client, db, monkeypatch
    ):
        """The highest-volume paywall encounter, and the easiest to miss.

        Locked editions render as a *count*, not as clickable rows, so an in-app
        free user never reaches the 403 surfaces above — this impression is the
        only place they meet the gate. ``run_search`` is stubbed because the real
        path needs the Anthropic API; the gate itself is covered by
        ``accounts.access`` tests.
        """
        search = SearchHistory.objects.create(
            query="fire separation", parsed_params={}, result_count=1,
        )

        def _stub(*args, **kwargs):
            return {
                "success": True,
                "results": [],
                "error": None,
                "applicable_codes": ["OBC_2006"],
                "parsed_params": {},
                "top_results_metadata": [],
                "search_history_id": search.pk,
                "locked_editions": {"OBC_2012": 3, "OBC_2024": 1},
            }

        monkeypatch.setattr("web.views.search.run_search", _stub)
        response = client.post(reverse("web:search_results"), {"query": "fire separation"})
        assert response.status_code == 200

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.LOCKED_CONTENT_VIEW
        assert event.context["surface"] == "search_results"
        assert event.context["locked_editions"] == {"OBC_2012": 3, "OBC_2024": 1}
        assert event.context["locked_count"] == 4
        assert event.search_id == search.pk

    def test_search_with_nothing_locked_records_no_impression(
        self, client: Client, db, monkeypatch
    ):
        def _stub(*args, **kwargs):
            return {
                "success": True, "results": [], "error": None,
                "applicable_codes": [], "parsed_params": {},
                "top_results_metadata": [], "search_history_id": None,
                "locked_editions": {},
            }

        monkeypatch.setattr("web.views.search.run_search", _stub)
        client.post(reverse("web:search_results"), {"query": "fire separation"})
        assert not EngagementEvent.objects.exists()

    def test_allowed_edition_records_no_locked_event(
        self, client: Client, provision_fixtures
    ):
        # provision_fixtures widens the free tier to OBC_1997, so the same
        # request must produce a view event and no locked event.
        url = reverse(
            "web:provision_permalink_no_division",
            kwargs={"code_edition": "OBC_1997", "provision_id": "1.1.1.1.", "version": 0},
        )
        assert client.get(url).status_code == 200
        assert not EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.LOCKED_CONTENT_VIEW
        ).exists()


@pytest.mark.django_db
class TestSourceLinkBeaconWiring:
    """The results-list source-link beacon is client-side, so the only thing
    assertable server-side is that the wiring ships — but one detail of it is
    load-bearing enough to guard.

    Browser-verified 2026-07-23: 22 of the 42 external source links in a real
    result set carry Alpine's ``@click.stop``.  A bubble-phase document listener
    never sees those, so the handler must register on the **capture** phase.
    Dropping the trailing ``true`` silently halves capture — no error, no failing
    behaviour, just missing rows — which is exactly the kind of regression a test
    should catch.
    """

    def test_handler_ships_on_the_capture_phase(self, client: Client):
        # The search page moved to /search/ when / became the landing page.
        body = client.get(reverse("web:search")).content.decode()
        start = body.find("Source-link beacon for the results list")
        assert start != -1, "results-list source-link beacon handler is missing"
        handler = body[start:start + 2000]
        assert "surface: 'source_link'" in handler
        assert "result_link_click" in handler
        assert "}, true);" in handler, (
            "source-link beacon must register on the capture phase — the `ext` "
            "citation links call stopPropagation() and would otherwise be missed"
        )
