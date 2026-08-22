"""What ``/api/search`` sends back, exercised against real records.

The gap these tests close: every earlier test of this endpoint mocked
``format_search_results`` to ``[]``, so the endpoint was only ever asked to
serialise an empty list.  The formatter builds cards for the templates and
puts live Django model instances in them, which the JSON encoder refuses — so
a search that matched anything answered 500 and no test could see it.

Only the LLM parser is mocked here.  Everything below it is the real pipeline.
"""

import json
from unittest.mock import patch

import pytest
from django.test import Client

from api.schemas import flatten
from api.tests.test_integration import _create_obc_fixtures
from core.models import ApiKey, User

PARSED = {
    "date": "2024-06-01",
    "province": "ON",
    "keywords": ["fire", "separations"],
    "section_references": [],
}


@pytest.mark.django_db
class TestTheSearchResponse:
    def setup_method(self):
        self.client = Client()
        self.user = User.objects.create_user(email="pro@example.com", pro_courtesy=True)
        _, token = ApiKey.generate(self.user, "tests")
        self.headers = {"authorization": f"Bearer {token}"}
        _create_obc_fixtures()

    def _search(self, query="fire separations"):
        return self.client.post(
            "/api/search",
            data=json.dumps({"query": query}),
            content_type="application/json",
            headers=self.headers,
        )

    @patch("services.search_service.parse_user_query")
    def test_a_search_that_matches_is_answered(self, mock_parse):
        """The regression: a non-empty result set must serialise at all."""
        mock_parse.return_value = dict(PARSED)

        response = self._search()

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["results"], "a matching search returned nothing"

    @patch("services.search_service.parse_user_query")
    def test_every_field_a_caller_is_promised_is_present(self, mock_parse):
        """The docs and the answer are the same shape, or the docs are fiction."""
        mock_parse.return_value = dict(PARSED)

        row = self._search().json()["results"][0]

        assert set(row) == {
            "id",
            "title",
            "division",
            "edition",
            "edition_name",
            "parent_id",
            "url",
            "score",
            "match_type",
            "matched_terms",
            "matched_terms_indirect",
            "version",
        }

    @patch("services.search_service.parse_user_query")
    def test_a_result_names_the_text_without_carrying_it(self, mock_parse):
        """The map: enough to judge a match, and to ask for it by name.

        The text comes from ``/api/provision``, one provision to a request,
        which is what lets the ledger say what an account has taken.
        """
        mock_parse.return_value = dict(PARSED)

        rows = self._search().json()["results"]
        row = next(r for r in rows if r["id"] == "3.2.7.1.")

        assert row["edition"] == "OBC_2024"
        assert row["title"]
        assert row["version"]["effective_date"] == "2024-01-01"
        assert row["version"]["is_base"] is True

    @patch("services.search_service.parse_user_query")
    def test_the_url_names_the_version_that_matched(self, mock_parse):
        """A caller following the link must land on the text it was sent."""
        mock_parse.return_value = dict(PARSED)

        row = next(r for r in self._search().json()["results"] if r["id"] == "3.2.7.1.")

        assert row["url"].startswith("/provision/OBC_2024/B/3.2.7.1.")
        assert row["url"].rstrip("/").endswith("0")

    @patch("services.search_service.parse_user_query")
    def test_the_meta_states_what_ran(self, mock_parse):
        mock_parse.return_value = dict(PARSED)

        meta = self._search().json()["meta"]

        assert meta["query"] == "fire separations"
        assert meta["date"] == "2024-06-01"
        assert meta["province"] == "ON"
        assert meta["editions_searched"] == ["OBC_2024"]
        assert meta["result_count"] == len(self._search().json()["results"])

    @patch("services.search_service.parse_user_query")
    def test_an_explicit_date_is_the_date_reported(self, mock_parse):
        """The request's date overrides the parser, so meta must say so."""
        mock_parse.return_value = dict(PARSED)

        response = self.client.post(
            "/api/search",
            data=json.dumps({"query": "fire separations", "date": "2025-02-02"}),
            content_type="application/json",
            headers=self.headers,
        )

        assert response.json()["meta"]["date"] == "2025-02-02"

    @patch("services.search_service.parse_user_query")
    def test_nothing_leaks_that_was_not_named(self, mock_parse):
        """No model instance, and none of the page's furniture.

        The formatter's card carries ``provision``, ``rail``, ``compare_pair``
        and more. They exist for the templates. A caller that started reading
        one would be depending on the website's layout.
        """
        mock_parse.return_value = dict(PARSED)

        body = self._search().content.decode()

        for template_only in ("rail", "compare_pair", "score_explanation", "provision"):
            assert f'"{template_only}"' not in body
        # And no body text, which is the whole point of the split.
        assert '"html"' not in body


class TestFlatten:
    """Cards are how a person reads results; entries are how a program does."""

    def test_a_plain_result_passes_through(self):
        assert flatten([{"id": "9.8.7.", "score": 1}]) == [{"id": "9.8.7.", "score": 1}]

    def test_a_transition_pair_becomes_both_texts(self):
        old = {"id": "3.1.", "score": 2}
        new = {"id": "3.1.", "score": 3}
        card = {"result_type": "transition_compare", "versions": [old, new]}

        assert flatten([card]) == [new, old]

    def test_a_group_becomes_its_parts_and_not_the_card(self):
        """The card prints the parent's number over the top child's text.

        That reads correctly as a heading and would be false as a record, so
        the card itself never becomes an entry.
        """
        parent = {"id": "3.2.7.", "score": 5}
        child = {"id": "3.2.7.1.", "score": 9}
        card = {
            "id": "3.2.7.",
            "group_type": "parent_children",
            "score": 9,
            "parent_result": parent,
            "children": [{"id": "3.2.7.1.", "result": child}],
        }

        assert flatten([card]) == [child, parent]

    def test_a_context_child_that_did_not_match_is_not_a_result(self):
        card = {
            "group_type": "parent_children",
            "children": [{"id": "3.2.7.2.", "result": None}],
        }

        assert flatten([card]) == []

    def test_entries_come_back_in_score_order(self):
        cards = [{"id": "a", "score": 1}, {"id": "b", "score": 7}]

        assert [row["id"] for row in flatten(cards)] == ["b", "a"]


@pytest.mark.django_db
class TestTheCodesResponse:
    """``/api/codes`` names the editions ``meta.editions_searched`` reports."""

    def test_the_edition_key_is_the_one_search_answers_with(self):
        user = User.objects.create_user(email="pro2@example.com", pro_courtesy=True)
        _, token = ApiKey.generate(user, "tests")
        _create_obc_fixtures()

        rows = Client().get(
            "/api/codes", headers={"authorization": f"Bearer {token}"}
        ).json()["results"]

        assert "OBC_2024" in [row["id"] for row in rows]
