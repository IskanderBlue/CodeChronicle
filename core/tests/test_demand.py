"""Tests for demand capture — the "which edition do you need?" band.

The design rule under test throughout: the *need* is the required field and
the email is not. A submission that loses the need is a bug; a submission that
loses a malformed email is correct behaviour.
"""

import pytest
from django.urls import reverse

from core.models import EditionRequest, SearchHistory
from core.views.demand import MAX_REQUESTS_PER_IP_PER_DAY


@pytest.mark.django_db
class TestEditionRequest:
    def test_records_the_need_without_an_email(self, client):
        response = client.post(
            reverse("core:edition_request"), {"code_text": "NBC 2015"}
        )
        assert response.status_code == 200
        row = EditionRequest.objects.get()
        assert row.code_text == "NBC 2015"
        assert row.email == ""
        assert b"Recorded" in response.content

    def test_keeps_a_valid_email(self, client):
        client.post(
            reverse("core:edition_request"),
            {"code_text": "BCBC 2018", "email": "reader@example.com"},
        )
        assert EditionRequest.objects.get().email == "reader@example.com"

    def test_drops_a_malformed_email_but_keeps_the_need(self, client):
        """Losing the whole submission over the optional field is the bug."""
        client.post(
            reverse("core:edition_request"),
            {"code_text": "Alberta 2014", "email": "not-an-address"},
        )
        row = EditionRequest.objects.get()
        assert row.code_text == "Alberta 2014"
        assert row.email == ""

    def test_empty_need_is_refused_and_stores_nothing(self, client):
        response = client.post(reverse("core:edition_request"), {"code_text": "   "})
        assert response.status_code == 200
        assert EditionRequest.objects.count() == 0
        assert b"Tell us the code and year" in response.content

    def test_surface_is_recorded_and_unknown_values_fall_back(self, client):
        client.post(
            reverse("core:edition_request"),
            {"code_text": "NBC 2020", "surface": "rate_limit"},
        )
        client.post(
            reverse("core:edition_request"),
            {"code_text": "NBC 2025", "surface": "not-a-surface"},
        )
        surfaces = list(
            EditionRequest.objects.order_by("id").values_list("surface", flat=True)
        )
        assert surfaces == ["rate_limit", "landing"]

    def test_links_to_the_originating_search_when_it_exists(self, client):
        search = SearchHistory.objects.create(
            ip_address="203.0.113.4", query="fire", result_count=1
        )
        client.post(
            reverse("core:edition_request"),
            {"code_text": "NBC 2015", "search_id": str(search.pk)},
        )
        assert EditionRequest.objects.get().search_id == search.pk

    def test_a_stale_search_id_does_not_lose_the_submission(self, client):
        client.post(
            reverse("core:edition_request"),
            {"code_text": "NBC 2015", "search_id": "999999"},
        )
        row = EditionRequest.objects.get()
        assert row.code_text == "NBC 2015"
        assert row.search_id is None

    def test_over_limit_posts_are_accepted_silently_and_not_stored(self, client):
        for i in range(MAX_REQUESTS_PER_IP_PER_DAY):
            client.post(
                reverse("core:edition_request"), {"code_text": f"code {i}"}
            )
        response = client.post(
            reverse("core:edition_request"), {"code_text": "one too many"}
        )
        assert response.status_code == 200
        assert EditionRequest.objects.count() == MAX_REQUESTS_PER_IP_PER_DAY
        assert not EditionRequest.objects.filter(code_text="one too many").exists()

    def test_get_is_not_allowed(self, client):
        assert client.get(reverse("core:edition_request")).status_code == 405

    def test_the_band_appears_on_the_landing_page(self, client):
        body = client.get(reverse("core:about")).content.decode()
        assert "Which edition do you need?" in body
        assert 'name="code_text"' in body
