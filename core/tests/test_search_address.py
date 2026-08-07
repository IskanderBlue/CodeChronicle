"""The address bar holds the search that ran.

Results arrive by ``hx-post``, so the address does not change by itself. A
reader who reloads, bookmarks, or sends somebody the link gets whatever the
address says — and if it says ``/search/`` they get an empty page and have to
type the search again.

The round-trip test is the one that matters. The view writes an address and
the search page reads one, and they are different pieces of code: an address
that names a search the page cannot reproduce is worse than no address, so
nothing here trusts the header's text on its own.
"""

import re
from typing import Any

import pytest
from django.urls import reverse

#: A new search earns a history entry, so Back returns to the one before it.
HEADER = "HX-Push-Url"
#: Re-measuring the search already on screen does not.
REPLACE = "HX-Replace-Url"


def _stub_search(**overrides):
    """A search that succeeds and returns nothing, so the address is the subject."""
    def _run(query, **kwargs):
        result: dict[str, Any] = {
            "success": True, "results": [], "applicable_codes": [],
            "parsed_params": {}, "locked_editions": {},
            "match_threshold": kwargs.get("match_threshold"),
        }
        result.update(overrides)
        return result

    return _run


@pytest.mark.django_db
class TestTheAddressFollowsTheSearch:
    def test_a_search_rewrites_the_address(self, client, monkeypatch):
        monkeypatch.setattr("core.views.search.run_search", _stub_search())

        response = client.post(
            reverse("core:search_results"),
            {"query": "fire separation", "date": "2010-06-01"},
        )

        assert response[HEADER] == "/search/?q=fire+separation&d=2010-06-01"

    def test_the_date_is_the_one_the_search_used(self, client, monkeypatch):
        """The AS-OF picker overrides the date the parser reads out of the text.

        A query saying "1999" that ran at 2010-06-01 must not leave an address
        claiming 1999, or the reload answers a different question.
        """
        monkeypatch.setattr("core.views.search.run_search", _stub_search())

        response = client.post(
            reverse("core:search_results"),
            {"query": "guards in 1999", "date": "2010-06-01"},
        )

        assert "d=2010-06-01" in response[HEADER]
        assert "1999" not in response[HEADER].split("d=")[1]

    def test_no_date_posted_leaves_the_date_out(self, client, monkeypatch):
        """A seeded page with no ``?d=`` searches at the corpus default, which
        is the date this search used.  Writing a date in would invent one."""
        monkeypatch.setattr("core.views.search.run_search", _stub_search())

        response = client.post(reverse("core:search_results"), {"query": "guards"})

        assert response[HEADER] == "/search/?q=guards"

    def test_moving_the_relevance_floor_does_not_add_an_entry(self, client, monkeypatch):
        """The floor control re-posts through this view without changing the
        query or the date.  A history entry per drag would leave Back stepping
        through addresses that are all the same, which reads as Back broken.
        """
        monkeypatch.setattr("core.views.search.run_search", _stub_search())

        response = client.post(
            reverse("core:search_results"),
            {"query": "guards", "date": "2010-06-01", "match_threshold": "0.9"},
        )

        assert response[REPLACE] == "/search/?q=guards&d=2010-06-01"
        assert HEADER not in response

    def test_a_failed_search_leaves_the_address_alone(self, client, monkeypatch):
        """Nothing ran, so there is nothing to reproduce.  An address pointing
        at a search that failed reloads into the same failure."""
        def _failing(query, **kwargs):
            return {"success": False, "error": "no", "invalid_date": None}

        monkeypatch.setattr("core.views.search.run_search", _failing)

        response = client.post(reverse("core:search_results"), {"query": "guards"})

        assert HEADER not in response
        assert REPLACE not in response

    def test_the_address_reproduces_the_search(self, client, monkeypatch):
        """The round trip: follow what the view wrote and get the same search.

        Encoding is the part that fails quietly — a query with a space or an
        ampersand survives ``urlencode`` and must survive the read back.
        """
        monkeypatch.setattr("core.views.search.run_search", _stub_search())
        query = "fire separation & guards"

        posted = client.post(
            reverse("core:search_results"), {"query": query, "date": "2010-06-01"}
        )
        followed = client.get(posted[HEADER])

        assert followed.status_code == 200
        assert followed.context["initial_query"] == query
        assert str(followed.context["initial_date"]) == "2010-06-01"
        # And the page it lands on runs that search rather than waiting.
        assert "data-autorun-search" in followed.content.decode()

    def test_the_seeded_page_carries_the_date_into_the_form(self, client, monkeypatch):
        """The picker is what the search reads, so a seeded date that never
        reaches the field reloads at the default date instead."""
        monkeypatch.setattr("core.views.search.run_search", _stub_search())

        posted = client.post(
            reverse("core:search_results"), {"query": "guards", "date": "2010-06-01"}
        )
        body = client.get(posted[HEADER]).content.decode()

        assert re.search(r'name="date"[^>]*value="2010-06-01"', body)
