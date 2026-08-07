"""Tests for the edition-request announcement.

This command writes to real people, and the failures it can have are the kind
nobody notices until a reader complains: two copies of one announcement, a
message about an edition somebody never asked for, or a send that goes out
while the operator thought they were reading a report.

So the properties here are about restraint. What it does not do matters more
than what it does.
"""

import pytest
from django.conf import settings
from django.contrib.sites.models import Site
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import EditionRequest

ABOUT = "OBC 1997"
NEWS = "The 1997 Ontario Building Code is now on CodeChronicle."


def _announce(**extra):
    """Run the command with the arguments every call needs."""
    options = {
        "about": ABOUT,
        "news": NEWS,
        "link": "https://www.codechronicle.ca/search/?q=guards&d=1999-06-01",
        "match": "1997",
    }
    options.update(extra)
    call_command("notify_edition_requests", **options)


def _asked(text="the 1997 OBC", email="reader@example.com"):
    return EditionRequest.objects.create(code_text=text, email=email)


@pytest.mark.django_db
class TestItPrintsBeforeItSends:
    def test_a_dry_run_sends_nothing(self):
        """The default is a report.  An accidental send to every address in
        the table cannot be taken back."""
        _asked()

        _announce()

        assert mail.outbox == []

    def test_a_dry_run_records_nothing(self):
        """A row stamped without a send would silence a reader who was never
        written to — and the stamp is what stops the real send finding them."""
        row = _asked()

        _announce()

        row.refresh_from_db()
        assert row.notified_at is None
        assert row.notified_about == []

    def test_sending_needs_the_flag(self):
        _asked()

        _announce(send=True)

        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestNobodyHearsItTwice:
    def test_a_notified_row_is_skipped_on_a_second_run(self):
        """The card's own test.  A re-run after a failure must reach the
        people the first run missed, and nobody else."""
        _asked()

        _announce(send=True)
        _announce(send=True)

        assert len(mail.outbox) == 1

    def test_the_stamp_names_what_they_were_told(self):
        row = _asked()

        _announce(send=True)

        row.refresh_from_db()
        assert row.notified_about == [ABOUT]
        assert row.notified_at is not None

    def test_a_row_can_still_hear_about_another_edition(self):
        """A stamp per edition, not one stamp per row.  Somebody who asked for
        two editions is owed two messages, and a single timestamp would spend
        the row on the first one."""
        row = _asked(text="the 1997 and 2012 OBC")

        _announce(send=True)
        _announce(about="OBC 2012", news="OBC 2012 has landed.", match="2012", send=True)

        row.refresh_from_db()
        assert row.notified_about == [ABOUT, "OBC 2012"]
        assert len(mail.outbox) == 2

    def test_force_writes_again(self):
        _asked()

        _announce(send=True)
        _announce(send=True, force=True)

        assert len(mail.outbox) == 2

    def test_one_address_across_two_requests_gets_one_message(self):
        """Two copies of one announcement reads as a mailing list, which is
        what we said this was not.  Both rows are still stamped."""
        first = _asked(text="the 1997 OBC")
        second = _asked(text="OBC 1997 please")

        _announce(send=True)

        assert len(mail.outbox) == 1
        for row in (first, second):
            row.refresh_from_db()
            assert row.notified_about == [ABOUT]


@pytest.mark.django_db
class TestItOnlyWritesToThePeopleChosen:
    def test_a_request_outside_the_selection_is_untouched(self):
        """A request for the BC code is not permission to announce an Ontario
        edition.  The Privacy Policy says so."""
        other = EditionRequest.objects.create(
            code_text="BC building code 2018", email="bc@example.com"
        )

        _announce(send=True)

        other.refresh_from_db()
        assert mail.outbox == []
        assert other.notified_about == []

    def test_a_request_with_no_address_is_skipped(self):
        """The address was optional on purpose; the need was the valuable
        field.  A row without one is not a failure."""
        row = _asked(email="")

        _announce(send=True)

        row.refresh_from_db()
        assert mail.outbox == []
        assert row.notified_at is None

    def test_it_refuses_to_choose_the_recipients_itself(self):
        """``code_text`` is free text.  No parser should decide that "the 1990
        OBC" is answered by an OBC 1997 load, so a human must select."""
        _asked()

        with pytest.raises(CommandError):
            call_command("notify_edition_requests", about=ABOUT, news=NEWS, link="x")

        assert mail.outbox == []


@pytest.mark.django_db
class TestTheMessage:
    def test_it_carries_the_news_the_link_and_the_boilerplate(self):
        _asked()

        _announce(send=True)

        body = mail.outbox[0].body
        assert NEWS in body
        assert "https://www.codechronicle.ca/search/?q=guards&d=1999-06-01" in body
        assert "privacy@codechronicle.ca" in body
        assert "CodeChronicle publishes historical Canadian building codes" in body

    def test_the_subject_names_the_edition(self):
        _asked()

        _announce(send=True)

        assert ABOUT in mail.outbox[0].subject

    def test_an_unconfigured_site_row_is_refused(self):
        """Django ships the Site row reading "example.com" and nothing in the
        app writes to it.  The resulting link is dead, the message still
        sends, and the only person who finds out is the reader."""
        Site.objects.filter(pk=settings.SITE_ID).update(domain="example.com")
        _asked()

        with pytest.raises(CommandError):
            _announce(link="", search="guards", date="1999-06-01", send=True)

        assert mail.outbox == []

    def test_a_search_can_stand_in_for_a_link(self):
        """The link is per-send, so a helper builds one rather than asking the
        sender to hand-write a URL.  It must carry the date: the picker
        overrides the date the parser reads, so a link without one answers a
        1999 question at the corpus default."""
        Site.objects.filter(pk=settings.SITE_ID).update(domain="www.codechronicle.ca")
        _asked()

        _announce(link="", search="guards and handrails", date="1999-06-01", send=True)

        body = mail.outbox[0].body
        assert (
            "https://www.codechronicle.ca/search/?q=guards+and+handrails&d=1999-06-01"
            in body
        )

    def test_it_refuses_a_message_with_nowhere_to_go(self):
        _asked()

        with pytest.raises(CommandError):
            _announce(link="", send=True)

        assert mail.outbox == []
