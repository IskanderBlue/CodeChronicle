"""What the website records about the text it hands over.

The ledger answers one question: which provision texts does this account hold?
Every test here defends one of the ways that answer goes quietly wrong — a key
spelled differently from the API's, a heading counted as text, a page render
inflating a repeat count, or a failure that reaches the reader.
"""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.utils import timezone

from api.provisions import record_fetch
from core.insights import ledger_health, reading_coverage
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
    ProvisionFetch,
    User,
)
from core.reading_ledger import keys_for, record_versions


@pytest.fixture
def corpus(db):
    """One edition, one article, three versions — two with text, one without."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2012", year=2012, effective_date=date(2012, 1, 1)
    )
    article = CodeEditionProvision.objects.create(
        edition=edition, provision_id="9.8.1.", level="article", division="B"
    )
    heading = CodeEditionProvision.objects.create(
        edition=edition, provision_id="9.8.", level="subsection", division="B"
    )
    return {
        "edition": edition,
        "with_text": CodeEditionProvisionVersion.objects.create(
            provision=article, version=0,
            effective_date=date(2012, 1, 1), html="<p>a guard shall…</p>",
        ),
        "also_with_text": CodeEditionProvisionVersion.objects.create(
            provision=article, version=1,
            effective_date=date(2014, 1, 1), html="<p>a guard shall not…</p>",
        ),
        "heading": CodeEditionProvisionVersion.objects.create(
            provision=heading, version=0,
            effective_date=date(2012, 1, 1), html="",
        ),
    }


def _request(user):
    request = RequestFactory().get("/provision/OBC_2012/B/9.8.1./v0/")
    request.user = user
    return request


@pytest.fixture
def reader(db):
    return User.objects.create_user(email="reader@example.com", pro_courtesy=True)


@pytest.mark.django_db
class TestWhatCountsAsDelivered:
    def test_a_heading_is_not_text(self, corpus, reader):
        """Every division, part, section and subsection has an empty body on
        purpose.  Recording one would inflate coverage with nothing a reader
        could copy, against a denominator measured the other way."""
        record_versions(_request(reader), [corpus["heading"]])

        assert ProvisionFetch.objects.count() == 0

    def test_every_rendered_text_is_recorded_not_only_the_one_asked_for(
        self, corpus, reader
    ):
        """The failure this ledger was built to fix: a permalink names one
        provision and renders up to forty, so recording the name reported an
        account served the whole corpus as holding about 2% of it."""
        record_versions(
            _request(reader), [corpus["with_text"], corpus["also_with_text"]]
        )

        assert ProvisionFetch.objects.count() == 2

    def test_an_anonymous_reader_writes_nothing(self, corpus):
        """An anonymous response is stored at the edge and never reaches
        Django, so an anonymous ledger would be full of holes it could not
        report.  Anonymous also means free tier, which we publish on purpose."""
        record_versions(_request(AnonymousUser()), [corpus["with_text"]])

        assert ProvisionFetch.objects.count() == 0


@pytest.mark.django_db
class TestTheKeyMatchesTheApi:
    def test_the_edition_is_spelled_the_way_a_permalink_spells_it(
        self, corpus, reader
    ):
        """``OBC_2012``, not ``OBC``.  A different spelling misses the unique
        constraint, so the account's ledger splits in two and its coverage
        halves — a corruption that reads as a well-behaved reader."""
        assert keys_for([corpus["with_text"]]) == [("OBC_2012", "B", "9.8.1.", 0)]

    def test_the_api_and_the_website_share_one_row(self, corpus, reader):
        """The same text through both surfaces is one text held, not two.
        ``coverage`` counts distinct texts, so a second row would overstate it."""
        record_fetch(reader, corpus["with_text"])
        record_versions(_request(reader), [corpus["with_text"]])

        assert ProvisionFetch.objects.count() == 1
        row = ProvisionFetch.objects.get()
        assert row.fetch_count == 2
        # The surface that delivered it FIRST, which the repeat never rewrites.
        assert row.source == ProvisionFetch.Source.API


@pytest.mark.django_db
class TestRepeats:
    def test_a_second_visit_increments_rather_than_inserting(self, corpus, reader):
        record_versions(_request(reader), [corpus["with_text"]])
        record_versions(_request(reader), [corpus["with_text"]])

        row = ProvisionFetch.objects.get()
        assert row.fetch_count == 2

    def test_the_first_seen_date_does_not_move(self, corpus, reader):
        """``first_fetched_at`` dates the novelty, and novelty is the signal.
        A repeat that moved it would make a returning reader look new."""
        record_versions(_request(reader), [corpus["with_text"]])
        first = ProvisionFetch.objects.get().first_fetched_at

        record_versions(_request(reader), [corpus["with_text"]])

        row = ProvisionFetch.objects.get()
        assert row.first_fetched_at == first
        assert row.last_fetched_at >= first

    def test_one_page_counts_once_even_when_it_repeats_a_version(
        self, corpus, reader
    ):
        """The keys are a set.  A page that renders one version twice delivered
        it once."""
        record_versions(
            _request(reader), [corpus["with_text"], corpus["with_text"]]
        )

        assert ProvisionFetch.objects.get().fetch_count == 1


@pytest.mark.django_db
class TestAFailureNeverReachesTheReader:
    def test_a_broken_write_does_not_raise(self, corpus, reader, monkeypatch):
        """A ledger failure must never break a read.  Same contract as
        ``core.events.record_event``."""
        def explode(*args, **kwargs):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(ProvisionFetch.objects, "bulk_create", explode)

        record_versions(_request(reader), [corpus["with_text"]])

        assert ProvisionFetch.objects.count() == 0

    def test_a_broken_write_reports_nothing_recorded(
        self, corpus, reader, monkeypatch
    ):
        """It answers 0 rather than a part count.  The writes are not one
        transaction, so after an exception the number written is unknown, and a
        watch that guesses low raises an alarm where one that guesses high
        hides it."""
        def explode(*args, **kwargs):
            raise RuntimeError("the database went away")

        monkeypatch.setattr(ProvisionFetch.objects, "bulk_create", explode)

        delivered, recorded = record_versions(
            _request(reader), [corpus["with_text"], corpus["also_with_text"]]
        )

        assert delivered == 2
        assert recorded == 0


@pytest.mark.django_db
class TestWhatItReportsBack:
    """The two counts a caller stamps on its view event, so that a *partial*
    ledger failure is visible.  ``ledger_health`` compares whole days, and a
    page that delivers forty texts and records three is not a silent day."""

    def test_a_working_write_reports_what_it_delivered(self, corpus, reader):
        delivered, recorded = record_versions(
            _request(reader), [corpus["with_text"], corpus["also_with_text"]]
        )

        assert (delivered, recorded) == (2, 2)

    def test_a_heading_is_delivered_by_neither_count(self, corpus, reader):
        """``delivered`` is measured exactly as ``recorded`` is.  Counting the
        versions instead would report a shortfall on every page carrying a
        heading, which is every container page in the product."""
        delivered, recorded = record_versions(
            _request(reader), [corpus["with_text"], corpus["heading"]]
        )

        assert (delivered, recorded) == (1, 1)

    def test_an_anonymous_reader_is_not_a_shortfall(self, corpus):
        """``record_reads`` answers 0 for an anonymous reader by design.  The
        watch counts signed-in readers only, or every anonymous read would
        report as a total ledger failure."""
        delivered, recorded = record_versions(
            _request(AnonymousUser()), [corpus["with_text"]]
        )

        assert (delivered, recorded) == (1, 0)


@pytest.mark.django_db
class TestTheSurfaceIsNamed:
    def test_a_row_without_a_surface_is_refused(self, reader):
        """Leaving the model default off is not enough: Django writes an
        implicit empty string, and such a row counts as neither surface.  The
        database refuses it instead."""
        with pytest.raises(IntegrityError), transaction.atomic():
            ProvisionFetch.objects.create(
                user=reader, code_edition="OBC_2012", division="B",
                provision_id="9.8.1.", version=0,
            )

    def test_the_website_records_itself_as_the_website(self, corpus, reader):
        record_versions(_request(reader), [corpus["with_text"]])

        assert ProvisionFetch.objects.get().source == ProvisionFetch.Source.WEB


@pytest.mark.django_db
class TestTheReadout:
    def test_the_two_surfaces_are_counted_apart(self, corpus, reader):
        """One curve over both is a curve over a population that does not
        exist: a website page delivers texts nobody asked for individually."""
        record_versions(_request(reader), [corpus["with_text"]])
        record_fetch(reader, corpus["also_with_text"])

        row = reading_coverage()[0]
        assert row["web_held"] == 1
        assert row["api_held"] == 1
        assert row["held"] == 2

    def test_sittings_come_from_the_gaps(self, corpus, reader):
        """Derived, not stored.  A run id minted per session would measure
        ``SESSION_COOKIE_AGE`` — two weeks here — so a consultant who stays
        signed in would score the single run that means "recorder"."""
        record_versions(_request(reader), [corpus["with_text"]])
        record_versions(_request(reader), [corpus["also_with_text"]])
        assert reading_coverage()[0]["sittings"] == 1

        stale = timezone.now() - timedelta(hours=3)
        ProvisionFetch.objects.filter(provision_id="9.8.1.", version=0).update(
            first_fetched_at=stale
        )
        assert reading_coverage()[0]["sittings"] == 2


@pytest.mark.django_db
class TestTheLedgerWatch:
    """The ledger swallows failures, so a second record has to say it is alive."""

    def _view_event(self, user, **context):
        return EngagementEvent.objects.create(
            user=user,
            event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW,
            context=context,
        )

    def test_views_without_writes_are_the_alarm(self, reader):
        self._view_event(reader)

        health = ledger_health()
        assert health["days_with_views"] == 1
        assert health["days_with_ledger"] == 0
        assert health["silent_days"] == 1

    def test_a_quiet_week_is_not_the_alarm(self, reader):
        """Both at zero means nobody read anything, which is not a fault."""
        health = ledger_health()
        assert health["silent_days"] == 0

    def test_a_working_ledger_is_silent_on_no_day(self, corpus, reader):
        self._view_event(reader)
        record_versions(_request(reader), [corpus["with_text"]])

        assert ledger_health()["silent_days"] == 0

    def test_a_page_that_records_less_than_it_delivered_is_the_alarm(
        self, corpus, reader
    ):
        """The failure days cannot see.  The write below gives this day a
        ledger entry, so ``silent_days`` passes it; the two counts on the
        request are what catch it."""
        self._view_event(reader, delivered=40, recorded=3)
        record_versions(_request(reader), [corpus["with_text"]])

        health = ledger_health()
        assert health["silent_days"] == 0
        assert health["shortfall_requests"] == 1
        assert health["last_shortfall"] is not None

    def test_a_page_that_recorded_everything_is_not(self, reader):
        self._view_event(reader, delivered=40, recorded=40)

        assert ledger_health()["shortfall_requests"] == 0

    def test_the_counts_compare_as_numbers_not_as_text(self, reader):
        """9 is fewer than 10.  Comparing the JSON values directly would order
        them as text and read this as a shortfall."""
        self._view_event(reader, delivered=9, recorded=10)

        assert ledger_health()["shortfall_requests"] == 0

    def test_a_surface_that_does_not_report_is_not_counted(self, reader):
        """Only the bulk surfaces stamp these keys.  An event without them
        must drop out rather than read as zero recorded."""
        self._view_event(reader)

        assert ledger_health()["shortfall_requests"] == 0

    def test_an_anonymous_read_is_not_a_shortfall(self):
        """The ledger records signed-in readers only, so an anonymous request
        always delivers text and records none.  Counting those would report
        every anonymous read on the site as a partial failure."""
        EngagementEvent.objects.create(
            user=None,
            event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW,
            context={"delivered": 12, "recorded": 0},
        )

        assert ledger_health()["shortfall_requests"] == 0
