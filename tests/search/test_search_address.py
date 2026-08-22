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

import json
import re
from typing import Any

import pytest
from django.urls import reverse

from search.service import run_search

#: A new search earns a history entry, so Back returns to the one before it.
HEADER = "HX-Push-Url"
#: Re-measuring the search already on screen does not.
REPLACE = "HX-Replace-Url"


def _stub_search(**parsed):
    """A search that succeeds and returns nothing, so the address is the subject.

    ``parsed`` lands in ``parsed_params`` alongside the building the view
    passed in — which is what ``search.service`` really does, since
    it writes the building into ``params`` before the search runs and the view
    reads the effective one back out of the result.
    """
    def _run(query, **kwargs):
        params: dict[str, Any] = dict(kwargs.get("building") or {})
        params.update(parsed)
        return {
            "success": True, "results": [], "applicable_codes": [],
            "parsed_params": params, "locked_editions": {},
            "match_threshold": kwargs.get("match_threshold"),
        }

    return _run


@pytest.mark.django_db
class TestTheAddressCarriesTheBuilding:
    """The building changes the order of the answer, so an address without it
    reproduces the words and not the page."""

    def test_the_address_names_the_building_the_search_ranked_by(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        response = client.post(
            reverse("web:search_results"),
            {
                "query": "guards",
                "date": "2010-06-01",
                "occupancy": "residential",
                "storeys": "4",
            },
        )

        assert "occupancy=residential" in response[HEADER]
        assert "storeys=4" in response[HEADER]

    def test_an_occupancy_the_parser_read_reaches_the_address(
        self, client, monkeypatch
    ):
        """The reader named a building in words and set no control.  A link
        that dropped the occupancy would rank differently from the page that
        handed it out."""
        monkeypatch.setattr(
            "web.views.search.run_search",
            _stub_search(occupancy="assembly"),
        )

        response = client.post(
            reverse("web:search_results"), {"query": "guards in a theatre"}
        )

        assert "occupancy=assembly" in response[HEADER]

    def test_changing_the_building_earns_a_history_entry(self, client, monkeypatch):
        """The building lives in the search form, so changing it means pressing
        Search.  The address that results differs from the one before it, so
        Back has somewhere real to return to.  The relevance floor is the
        opposite case: it re-posts by itself, from the results partial.

        This is also why the refinement test cannot key on the building fields
        — they now ride on *every* search, and testing for their presence
        would stop history entries being written at all.
        """
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        response = client.post(
            reverse("web:search_results"),
            {"query": "guards", "date": "2010-06-01", "occupancy": "residential"},
        )

        assert HEADER in response
        assert REPLACE not in response

    def test_the_floor_control_still_carries_the_building_through(
        self, client, monkeypatch
    ):
        """The floor control re-posts with hx-include="#search-form", which
        now contains the building.  A re-measure that dropped it would
        re-rank the page against a different building than the one on screen.
        """
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        response = client.post(
            reverse("web:search_results"),
            {
                "query": "guards",
                "date": "2010-06-01",
                "occupancy": "residential",
                "storeys": "4",
                "match_threshold": "0.9",
            },
        )

        assert "occupancy=residential" in response[REPLACE]
        assert "storeys=4" in response[REPLACE]
        assert HEADER not in response

    def test_a_building_nobody_stated_leaves_the_address_alone(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        response = client.post(reverse("web:search_results"), {"query": "guards"})

        assert response[HEADER] == "/search/?q=guards"

    def test_an_unusable_measurement_is_dropped_rather_than_guessed(
        self, client, monkeypatch
    ):
        """A hand-edited address, or a control posting an empty field.  A
        default here would be a guess about somebody's building."""
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        response = client.post(
            reverse("web:search_results"),
            {"query": "guards", "occupancy": "residential", "storeys": "not a number"},
        )

        assert "occupancy=residential" in response[HEADER]
        assert "storeys" not in response[HEADER]

    def test_an_invented_occupancy_is_refused(self, client, monkeypatch):
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        response = client.post(
            reverse("web:search_results"),
            {"query": "guards", "occupancy": "spaceport"},
        )

        assert "occupancy" not in response[HEADER]

    def test_the_address_reproduces_the_ranking(self, client, monkeypatch):
        """The round trip.  A history click must land on the same order, which
        is the whole reason the building is in the address."""
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        posted = client.post(
            reverse("web:search_results"),
            {
                "query": "guards",
                "date": "2010-06-01",
                "occupancy": "residential",
                "storeys": "4",
            },
        )
        followed = client.get(posted[HEADER])

        assert followed.status_code == 200
        assert followed.context["initial_building"] == {
            "occupancy": "residential",
            "storeys": 4,
        }
        # And the form is filled in, or the auto-run posts an empty building
        # and the page contradicts its own address.
        body = followed.content.decode()
        assert re.search(r'<option value="residential" selected>', body)
        assert re.search(r'name="storeys"[^>]*value="4"', body)
        assert "data-autorun-search" in body


@pytest.mark.django_db
class TestTheFormLearnsWhatTheParserRead:
    """The size fields appear only once an occupancy is named, and a reader
    who typed "house" has named one — in words, not in the dropdown.

    Without this the boost would only ever move an assembly, care or
    high-hazard query, because those are the only ones the occupancy settles
    on its own.
    """

    def test_the_parsers_reading_is_announced_to_the_form(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            "web.views.search.run_search",
            _stub_search(occupancy="residential"),
        )

        response = client.post(
            reverse("web:search_results"), {"query": "guards in a house"}
        )

        assert json.loads(response["HX-Trigger"]) == {
            "cc-occupancy-read": {"occupancy": "residential"}
        }

    def test_a_reader_who_chose_is_never_overwritten(self, client, monkeypatch):
        """The whole contract of "Read it from my query" runs one way. A
        reader who picked mercantile must not have the model's reading of
        their words pushed back into the control."""
        monkeypatch.setattr(
            "web.views.search.run_search",
            _stub_search(occupancy="residential"),
        )

        response = client.post(
            reverse("web:search_results"),
            {"query": "guards in a house", "occupancy": "mercantile"},
        )

        assert "HX-Trigger" not in response

    def test_a_query_naming_no_building_announces_nothing(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(
            "web.views.search.run_search", _stub_search()
        )

        response = client.post(
            reverse("web:search_results"), {"query": "what is a mezzanine"}
        )

        assert "HX-Trigger" not in response


@pytest.mark.django_db
class TestTheModelOnlyFillsABlank:
    """The reader's stated building always wins over the parser's reading.

    The BUILDING strip's default option says "Read from my query", and that
    promise runs one way only: a blank field lets the parser answer, and a
    filled one is never overruled.
    """

    def _params(self, monkeypatch, posted, *, model_says):
        """Run the real service with a stubbed parser, and return its params."""
        captured: dict[str, Any] = {}

        def _parse(query):
            return {
                "date": "2010-06-01", "keywords": ["guards"],
                "direct_keywords": ["guards"], "province": "ON",
                **model_says,
            }

        def _execute(params, **kwargs):
            captured.update(params)
            return {
                "results": [], "applicable_codes": [], "top_results_metadata": [],
                "locked_editions": {}, "locked_preview": [],
            }

        monkeypatch.setattr("search.service.parse_user_query", _parse)
        monkeypatch.setattr("search.service.execute_search", _execute)
        run_search("guards", building=posted)
        return captured

    def test_a_blank_field_leaves_the_parsers_reading(self, monkeypatch):
        params = self._params(
            monkeypatch, {}, model_says={"occupancy": "assembly"}
        )

        assert params["occupancy"] == "assembly"

    def test_a_stated_occupancy_overrules_the_parser(self, monkeypatch):
        params = self._params(
            monkeypatch,
            {"occupancy": "residential"},
            model_says={"occupancy": "assembly"},
        )

        assert params["occupancy"] == "residential"

    def test_the_parser_supplies_no_measurement_to_overrule(self, monkeypatch):
        """The tool schema does not offer a size and the prompt forbids one.
        A measurement reaches the search only when the reader typed it."""
        params = self._params(monkeypatch, {}, model_says={})

        assert "storeys" not in params
        assert "area_m2" not in params

    def test_a_stated_measurement_reaches_the_search(self, monkeypatch):
        params = self._params(
            monkeypatch,
            {"storeys": 4, "area": 140.0, "area_unit": "m2", "area_m2": 140.0},
            model_says={},
        )

        assert params["storeys"] == 4
        assert params["area_m2"] == 140.0


@pytest.mark.django_db
class TestTheAddressFollowsTheSearch:
    def test_a_search_rewrites_the_address(self, client, monkeypatch):
        monkeypatch.setattr("web.views.search.run_search", _stub_search())

        response = client.post(
            reverse("web:search_results"),
            {"query": "fire separation", "date": "2010-06-01"},
        )

        assert response[HEADER] == "/search/?q=fire+separation&d=2010-06-01"

    def test_the_date_is_the_one_the_search_used(self, client, monkeypatch):
        """The AS-OF picker overrides the date the parser reads out of the text.

        A query saying "1999" that ran at 2010-06-01 must not leave an address
        claiming 1999, or the reload answers a different question.
        """
        monkeypatch.setattr("web.views.search.run_search", _stub_search())

        response = client.post(
            reverse("web:search_results"),
            {"query": "guards in 1999", "date": "2010-06-01"},
        )

        assert "d=2010-06-01" in response[HEADER]
        assert "1999" not in response[HEADER].split("d=")[1]

    def test_no_date_posted_leaves_the_date_out(self, client, monkeypatch):
        """A seeded page with no ``?d=`` searches at the corpus default, which
        is the date this search used.  Writing a date in would invent one."""
        monkeypatch.setattr("web.views.search.run_search", _stub_search())

        response = client.post(reverse("web:search_results"), {"query": "guards"})

        assert response[HEADER] == "/search/?q=guards"

    def test_moving_the_relevance_floor_does_not_add_an_entry(self, client, monkeypatch):
        """The floor control re-posts through this view without changing the
        query or the date.  A history entry per drag would leave Back stepping
        through addresses that are all the same, which reads as Back broken.
        """
        monkeypatch.setattr("web.views.search.run_search", _stub_search())

        response = client.post(
            reverse("web:search_results"),
            {"query": "guards", "date": "2010-06-01", "match_threshold": "0.9"},
        )

        assert response[REPLACE] == "/search/?q=guards&d=2010-06-01"
        assert HEADER not in response

    def test_a_failed_search_leaves_the_address_alone(self, client, monkeypatch):
        """Nothing ran, so there is nothing to reproduce.  An address pointing
        at a search that failed reloads into the same failure."""
        def _failing(query, **kwargs):
            return {"success": False, "error": "no", "invalid_date": None}

        monkeypatch.setattr("web.views.search.run_search", _failing)

        response = client.post(reverse("web:search_results"), {"query": "guards"})

        assert HEADER not in response
        assert REPLACE not in response

    def test_the_address_reproduces_the_search(self, client, monkeypatch):
        """The round trip: follow what the view wrote and get the same search.

        Encoding is the part that fails quietly — a query with a space or an
        ampersand survives ``urlencode`` and must survive the read back.
        """
        monkeypatch.setattr("web.views.search.run_search", _stub_search())
        query = "fire separation & guards"

        posted = client.post(
            reverse("web:search_results"), {"query": query, "date": "2010-06-01"}
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
        monkeypatch.setattr("web.views.search.run_search", _stub_search())

        posted = client.post(
            reverse("web:search_results"), {"query": "guards", "date": "2010-06-01"}
        )
        body = client.get(posted[HEADER]).content.decode()

        assert re.search(r'name="date"[^>]*value="2010-06-01"', body)
