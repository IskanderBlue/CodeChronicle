"""Tests for the search-history page.

The property that matters is that a history entry replays the search it
records.  The AS-OF picker overrides whatever the parser reads out of the
query text, so a link carrying only the words re-runs them at the default
date and returns a different edition's text — with no error, and under the
date the same card displays.  On a product whose claim is "as it read on that
date", that is the worst shape a bug can take.
"""

import re
from datetime import date

import pytest

from core.models import SearchHistory, User


@pytest.fixture
def reader(db):
    return User.objects.create_user(email="reader@example.com", password="pw")


def _entry(user: User, query: str, params: dict) -> SearchHistory:
    return SearchHistory.objects.create(user=user, query=query, parsed_params=params)


@pytest.mark.django_db
class TestHistoryLinks:
    def test_the_link_carries_the_date_the_search_ran_at(self, client, reader):
        _entry(
            reader,
            "guards and handrails for a stairway",
            {"date": "2010-06-01", "province": "ON", "keywords": ["guards"]},
        )
        client.force_login(reader)
        body = client.get("/history/").content.decode()
        assert "d=2010-06-01" in body
        # The urlencode filter percent-encodes the space; it does not use "+".
        assert "q=guards%20and%20handrails%20for%20a%20stairway" in body

    def test_the_date_is_the_one_the_card_displays(self, client, reader):
        """The card prints the date two lines below the link.  A link that
        replayed a different date would contradict the page itself."""
        _entry(reader, "spatial separation", {"date": "2024-12-31", "province": "ON"})
        client.force_login(reader)
        body = client.get("/history/").content.decode()
        assert "d=2024-12-31" in body
        assert body.count("2024-12-31") >= 2

    def test_an_entry_with_no_stored_date_still_links(self, client, reader):
        """Rows written before the picker existed, and parses that read no
        date, carry none.  The link degrades to the words rather than sending
        an empty parameter the search view would have to defend against."""
        _entry(reader, "fire separations", {"province": "ON"})
        client.force_login(reader)
        body = client.get("/history/").content.decode()
        # Match the link itself.  A bare "d=" also matches the SVG path
        # attributes the page is full of.
        href = re.search(r'href="(/search/\?q=[^"]*)"', body)
        assert href is not None
        assert href.group(1) == "/search/?q=fire%20separations"

    def test_the_page_needs_a_signed_in_reader(self, client, reader):
        _entry(reader, "anything", {"date": "2010-06-01"})
        response = client.get("/history/")
        assert response.status_code == 302

    def test_following_the_link_seeds_the_as_of_picker(self, client, reader):
        """The round trip, not the halves.

        The link is worth nothing unless the search page honours the date it
        carries, and the two ends are written in different files.
        """
        _entry(reader, "guards", {"date": "2010-06-01", "province": "ON"})
        client.force_login(reader)
        body = client.get("/history/").content.decode()
        href = re.search(r'href="(/search/\?q=[^"]*)"', body)
        assert href is not None

        followed = client.get(href.group(1).replace("&amp;", "&"))
        assert followed.status_code == 200
        assert followed.context["initial_date"] == date(2010, 6, 1)
        assert followed.context["initial_query"] == "guards"
