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

from core.models import SearchHistory, User, grouped_by_question, question_keys


@pytest.fixture
def reader(db):
    return User.objects.create_user(email="reader@example.com", password="pw")


def _entry(user: User, query: str, params: dict) -> SearchHistory:
    return SearchHistory.objects.create(user=user, query=query, parsed_params=params)


def _cards(body: str) -> list[str]:
    """The replay link of every card on the page, in render order."""
    return re.findall(r'href="(/search/\?q=[^"]*)"', body)


@pytest.mark.django_db
class TestHistoryGrouping:
    """A card is a *question* — the words and the date they ran at.

    The same definition ``core.middleware`` uses for the allowance.  Grouping
    on the words alone made the same question at two dates one card, which
    showed the later date and hid the earlier search from the reader who ran
    it.
    """

    def test_the_same_words_at_two_dates_are_two_cards(self, client, reader):
        _entry(reader, "guards", {"date": "2010-06-01", "province": "ON"})
        _entry(reader, "guards", {"date": "2015-06-01", "province": "ON"})
        client.force_login(reader)
        body = client.get("/history/").content.decode()

        cards = _cards(body)
        assert len(cards) == 2
        assert any("d=2010-06-01" in card for card in cards)
        assert any("d=2015-06-01" in card for card in cards)

    def test_the_same_question_twice_is_one_card(self, client, reader):
        _entry(reader, "guards", {"date": "2010-06-01", "province": "ON"})
        _entry(reader, "guards", {"date": "2010-06-01", "province": "ON"})
        client.force_login(reader)
        body = client.get("/history/").content.decode()

        assert len(_cards(body)) == 1
        assert "2×" in body

    def test_the_card_shows_the_latest_run_of_the_question(self, client, reader):
        """Re-running a question updates the card the reader comes back to.

        This is what carries a changed ranking parameter — the reader sets it
        on the search page, and the history card offers the setting they left.
        Nothing edits the stored row; the page reads the newest one.
        """
        _entry(reader, "guards", {"date": "2010-06-01", "keywords": ["guards"]})
        _entry(reader, "guards", {"date": "2010-06-01", "keywords": ["handrails"]})
        client.force_login(reader)
        body = client.get("/history/").content.decode()

        assert len(_cards(body)) == 1
        assert "handrails" in body

    def test_entries_with_no_stored_date_group_together(self, client, reader):
        """A parse that read no date leaves the key absent, so the grouping
        sees NULL.  Those are all one question — the same words at no stated
        date — and must not fan out into a card each."""
        _entry(reader, "fire separations", {"province": "ON"})
        _entry(reader, "fire separations", {"province": "ON"})
        client.force_login(reader)
        body = client.get("/history/").content.decode()

        assert len(_cards(body)) == 1

    def test_a_dated_run_does_not_absorb_an_undated_one(self, client, reader):
        _entry(reader, "fire separations", {"province": "ON"})
        _entry(reader, "fire separations", {"date": "2010-06-01", "province": "ON"})
        client.force_login(reader)
        body = client.get("/history/").content.decode()

        assert len(_cards(body)) == 2


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


class TestOneDefinitionOfAQuestion:
    """The allowance and the history page must count the same thing.

    ``core.middleware`` charges an anonymous reader per question; this page
    shows one card per question.  Each used to spell the key by hand.  If one
    widens and the other does not, a reader is charged for a search they
    cannot find in their own history, and nothing on either side fails.
    """

    def test_both_readers_of_the_definition_see_the_same_questions(self, reader):
        """Four rows, three questions: one repeat, and one date that differs."""
        _entry(reader, "guards", {"date": "2010-06-01"})
        _entry(reader, "guards", {"date": "2010-06-01"})  # the same question again
        _entry(reader, "guards", {"date": "2015-06-01"})  # same words, another date
        _entry(reader, "stairs", {"date": "2010-06-01"})  # other words, same date

        searches = SearchHistory.objects.filter(user=reader)

        assert set(question_keys(searches)) == {
            ("guards", "2010-06-01"),
            ("guards", "2015-06-01"),
            ("stairs", "2010-06-01"),
        }

        grouped = {
            (row["query"], row["query_date"])
            for row in grouped_by_question(searches)
        }
        assert grouped == set(question_keys(searches))

    def test_the_building_is_not_part_of_the_question(self, reader):
        """Re-ranking one question is not asking a second one.

        The address carries the building so that a reload reproduces the page.
        The question key must not, or the relevance-floor and building controls
        would each spend a search and each split a card.
        """
        _entry(reader, "guards", {"date": "2010-06-01", "occupancy": "residential"})
        _entry(reader, "guards", {"date": "2010-06-01", "occupancy": "business"})

        searches = SearchHistory.objects.filter(user=reader)
        assert set(question_keys(searches)) == {("guards", "2010-06-01")}
