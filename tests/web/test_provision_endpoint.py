"""Fetching a provision: the only route by which the API serves text."""

import json
from datetime import date

import pytest
from django.test import Client

from core.models import (
    ApiKey,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvisionFetch,
    User,
)
from tests.search.test_integration import _create_obc_fixtures


def _headers(user: User) -> dict[str, str]:
    _, token = ApiKey.generate(user, "tests")
    return {"authorization": f"Bearer {token}"}


@pytest.mark.django_db
class TestFetchingAProvision:
    def setup_method(self):
        self.client = Client()
        self.user = User.objects.create_user(email="pro@example.com", pro_courtesy=True)
        self.headers = _headers(self.user)
        _create_obc_fixtures()

    def _get(self, **params):
        params.setdefault("edition", "OBC_2024")
        params.setdefault("division", "B")
        params.setdefault("id", "3.2.7.1.")
        return self.client.get("/api/provision", params, headers=self.headers)

    def test_it_answers_with_the_text(self):
        response = self._get(on="2024-06-01")

        assert response.status_code == 200
        row = response.json()["results"][0]
        assert "fire separations" in row["html"].lower()
        assert row["id"] == "3.2.7.1."
        assert row["version"]["number"] == 0

    def test_the_search_no_longer_carries_the_text(self):
        """The map and the territory are different calls, on purpose.

        This is what makes a text countable: one request, one provision, one
        ledger row. A hundred texts to a search response could not be counted.
        """
        from unittest.mock import patch

        with patch("search.service.parse_user_query") as parse:
            parse.return_value = {
                "date": "2024-06-01",
                "province": "ON",
                "keywords": ["fire"],
                "section_references": [],
            }
            results = self.client.post(
                "/api/search",
                data=json.dumps({"query": "fire"}),
                content_type="application/json",
                headers=self.headers,
            ).json()["results"]

        assert results
        assert "html" not in results[0]
        assert "tables" not in results[0]

    def test_a_search_result_is_a_valid_request_as_it_stands(self):
        """The map's fields are the lookup's arguments, so nothing is composed."""
        from unittest.mock import patch

        with patch("search.service.parse_user_query") as parse:
            parse.return_value = {
                "date": "2024-06-01",
                "province": "ON",
                "keywords": ["fire"],
                "section_references": [],
            }
            row = self.client.post(
                "/api/search",
                data=json.dumps({"query": "fire"}),
                content_type="application/json",
                headers=self.headers,
            ).json()["results"][0]

        response = self.client.get(
            "/api/provision",
            {
                "edition": row["edition"],
                "division": row["division"],
                "id": row["id"],
                "version": row["version"]["number"],
            },
            headers=self.headers,
        )

        assert response.status_code == 200
        assert response.json()["results"][0]["id"] == row["id"]

    def test_no_date_reads_as_today(self):
        assert self._get().status_code == 200
        assert self._get().json()["meta"]["resolved_by"] == "in_force_on"

    def test_an_exact_version_can_be_pinned(self):
        payload = self._get(version=0).json()

        assert payload["meta"]["resolved_by"] == "requested"
        assert payload["meta"]["on"] is None

    def test_a_date_and_a_version_together_are_refused(self):
        """They can disagree, and guessing which was meant is how an exhibit
        ends up quoting a text that was not in force."""
        response = self._get(on="2024-06-01", version=0)

        assert response.status_code == 400
        assert "not both" in response.json()["error"]

    def test_an_unparsable_date_says_so(self):
        response = self._get(on="the nineties")

        assert response.status_code == 400
        assert "YYYY-MM-DD" in response.json()["error"]

    def test_a_date_before_the_provision_existed_finds_nothing(self):
        response = self._get(on="1985-01-01")

        assert response.status_code == 404
        assert "1985-01-01" in response.json()["error"]

    def test_an_unknown_provision_is_a_404_that_says_what_was_asked(self):
        response = self._get(id="99.99.99.")

        assert response.status_code == 404
        assert "99.99.99." in response.json()["error"]

    def test_it_needs_a_key(self):
        assert Client().get(
            "/api/provision", {"edition": "OBC_2024", "division": "B", "id": "3.2.7.1."}
        ).status_code == 401

    def test_the_tier_gate_still_applies(self):
        """A key changes how an account asks, never what it may read."""
        free = User.objects.create_user(email="free@example.com")
        # A key on an account with no subscription is refused before the
        # edition is even looked at, which is the 403 that matters here.
        response = self.client.get(
            "/api/provision",
            {"edition": "OBC_2024", "division": "B", "id": "3.2.7.1."},
            headers=_headers(free),
        )

        assert response.status_code == 403

    def test_a_division_less_edition_can_be_asked_for(self):
        """OBC 1997 has no divisions, so the division argument is empty.

        This is why these are query parameters: an empty path segment is not
        a path, and the website needed a second URL route to work around it.
        """
        existing = CodeEditionProvision.objects.first()
        assert existing is not None
        edition = existing.edition
        bare = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id="4.1.1.",
            level=CodeEditionProvision.Level.ARTICLE,
            division="",
        )
        CodeEditionProvisionVersion.objects.create(
            provision=bare,
            version=0,
            effective_date=date(2024, 1, 1),
            title="No division here",
            html="<p>Text.</p>",
        )

        response = self.client.get(
            "/api/provision",
            {"edition": "OBC_2024", "division": "", "id": "4.1.1."},
            headers=self.headers,
        )

        assert response.status_code == 200
        assert response.json()["results"][0]["division"] == ""


@pytest.mark.django_db
class TestTheFetchLedger:
    """What an account has taken, which is the signal volume cannot give."""

    def setup_method(self):
        self.client = Client()
        self.user = User.objects.create_user(email="pro@example.com", pro_courtesy=True)
        self.headers = _headers(self.user)
        _create_obc_fixtures()

    def _get(self, provision_id="3.2.7.1."):
        return self.client.get(
            "/api/provision",
            {"edition": "OBC_2024", "division": "B", "id": provision_id, "version": 0},
            headers=self.headers,
        )

    def test_a_fetch_is_recorded(self):
        self._get()

        row = ProvisionFetch.objects.get(user=self.user)
        assert row.provision_id == "3.2.7.1."
        assert row.code_edition == "OBC_2024"
        assert row.version == 0
        assert row.fetch_count == 1

    def test_the_same_text_again_is_a_repeat_not_a_new_row(self):
        """A high repeat rate is the ordinary shape of real use, so it has to
        be visible as one row counting up rather than as more coverage."""
        self._get()
        self._get()
        self._get()

        assert ProvisionFetch.objects.filter(user=self.user).count() == 1
        assert ProvisionFetch.objects.get(user=self.user).fetch_count == 3

    def test_each_new_provision_widens_the_coverage(self):
        self._get("3.2.7.1.")
        self._get("3.2.7.2.")

        assert ProvisionFetch.objects.filter(user=self.user).count() == 2

    def test_the_ledger_is_per_account(self):
        other = User.objects.create_user(email="other@example.com", pro_courtesy=True)
        self._get()

        assert ProvisionFetch.objects.filter(user=other).count() == 0

    def test_a_refused_fetch_records_nothing(self):
        """The ledger answers what an account holds, and a refusal delivered
        nothing to hold."""
        self.client.get(
            "/api/provision",
            {"edition": "OBC_2024", "division": "B", "id": "99.99.99."},
            headers=self.headers,
        )

        assert ProvisionFetch.objects.count() == 0

    def test_a_search_records_no_fetch(self):
        """A search says where to look. Nothing has been taken yet."""
        from unittest.mock import patch

        with patch("search.service.parse_user_query") as parse:
            parse.return_value = {
                "date": "2024-06-01",
                "province": "ON",
                "keywords": ["fire"],
                "section_references": [],
            }
            self.client.post(
                "/api/search",
                data=json.dumps({"query": "fire"}),
                content_type="application/json",
                headers=self.headers,
            )

        assert ProvisionFetch.objects.count() == 0
