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


@pytest.fixture
def provision_fixtures(db):
    """A division-less OBC 1997 provision with one in-force version."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="1997", year=1997,
        effective_date=date(1998, 4, 6), map_codes=[],
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


@pytest.mark.django_db
class TestProvisionPermalinkTracking:
    def test_records_provision_version_view(self, client: Client, provision_fixtures):
        version = provision_fixtures["version"]
        url = reverse(
            "core:provision_permalink_no_division",
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
        url = reverse("core:viewer_section_content")
        response = client.get(url, {
            "code": "OBC",
            "edition_id": "1997",
            "division": "",
            "provision_id": "1.1.1.1.",
            "query_date": "2020-01-01",
            "search_id": str(search.pk),
        })
        assert response.status_code == 200

        event = EngagementEvent.objects.get()
        assert event.event_type == EngagementEvent.EventType.PROVISION_VERSION_VIEW
        assert event.object_id == version.pk
        assert event.search_id == search.pk
        assert event.context["surface"] == "search_viewer"

    def test_bad_search_id_is_dropped_not_fatal(self, client: Client, provision_fixtures):
        url = reverse("core:viewer_section_content")
        response = client.get(url, {
            "code": "OBC", "edition_id": "1997", "division": "",
            "provision_id": "1.1.1.1.", "query_date": "2020-01-01",
            "search_id": "not-a-number",
        })
        assert response.status_code == 200
        event = EngagementEvent.objects.get()
        assert event.search_id is None


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
