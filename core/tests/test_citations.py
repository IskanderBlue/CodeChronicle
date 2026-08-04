"""Tests for the citation strings a reader pastes into their own work.

A citation is the one thing this product emits that nobody can check against
the page it came from — it is read months later, in a document we never see.
So the properties under test are the ones that are wrong *silently*: the day a
window ends, which text the URL opens, and what a citation says when a fact is
missing.
"""

from datetime import date

import pytest

from core.citations import LEGAL, REPORT, build_citations
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    Regulation,
)

ORIGIN = "https://www.codechronicle.ca"
RETRIEVED = date(2026, 8, 4)


@pytest.fixture
def enacted(db):
    """An OBC 2006 article with two versions, and the regulation that enacted it.

    The edition ends 1 January 2014, which is what closes the second version's
    otherwise open window — the case a version-only reading gets wrong.
    """
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code,
        edition_id="2006",
        year=2006,
        effective_date=date(2006, 12, 31),
        ineffective_date=date(2014, 1, 1),
    )
    Regulation.objects.create(
        edition=edition,
        reg_id="350/06",
        role=Regulation.Role.BASE,
        effective_date=date(2006, 12, 31),
    )
    provision = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.2.5.7.", level="article", division="B",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=provision,
        version=0,
        effective_date=date(2006, 12, 31),
        ineffective_date=date(2009, 1, 1),
        title="Fire Department Access Routes",
        html="<p>first</p>",
    )
    CodeEditionProvisionVersion.objects.create(
        provision=provision,
        version=1,
        effective_date=date(2009, 1, 1),
        ineffective_date=None,
        title="Fire Department Access Routes",
        html="<p>second</p>",
    )
    return provision


def _by_kind(provision, version, **kwargs):
    cites = build_citations(
        provision, version, origin=ORIGIN, retrieved=RETRIEVED, **kwargs
    )
    return {c.kind: c.text for c in cites}


@pytest.mark.django_db
class TestTheWindowEndsOnADayThatWasGoverned:
    """The half-open window is the trap: ``effective <= d < ineffective``."""

    def test_report_names_the_last_day_in_force_not_the_end_date(self, enacted):
        version = enacted.versions.get(version=0)
        text = _by_kind(enacted, version)[REPORT]
        # The stored end is 1 January 2009 — the first day the text did NOT
        # apply.  A citation that says "to 1 January 2009" claims the text
        # stood on a day it did not.
        assert "in force 31 December 2006 to 31 December 2008" in text
        assert "1 January 2009" not in text

    def test_an_open_version_closes_at_the_edition_end(self, enacted):
        version = enacted.versions.get(version=1)
        text = _by_kind(enacted, version)[REPORT]
        # The version carries no end date; the edition ends 1 January 2014.
        # Without the edition's end this reads "in force from 1 January 2009",
        # which reads as current for a text superseded twelve years ago.
        assert "in force 1 January 2009 to 31 December 2013" in text
        assert "in force from" not in text


@pytest.mark.django_db
class TestTheUrlOpensTheTextTheCitationQuotes:
    def test_the_url_names_this_version_not_the_canonical_one(self, enacted):
        version = enacted.versions.get(version=0)
        text = _by_kind(enacted, version)[REPORT]
        # v1 is canonical (highest version).  A citation that pins a date and
        # links to a different text sends the reader to words it does not
        # quote, so it links to its own version.
        assert f"{ORIGIN}/provision/OBC_2006/B/3.2.5.7./v0/" in text
        assert "/v1/" not in text

    def test_the_retrieval_date_is_stated(self, enacted):
        version = enacted.versions.get(version=0)
        text = _by_kind(enacted, version)[REPORT]
        assert "Retrieved 2026-08-04 from" in text


@pytest.mark.django_db
class TestTheLegalFormFollowsMcGill:
    def test_it_names_the_instrument_the_pinpoint_and_one_date(self, enacted):
        version = enacted.versions.get(version=0)
        text = _by_kind(enacted, version)[LEGAL]
        assert text == (
            "O Reg 350/06, Article 3.2.5.7. of Division B, "
            "as it appeared on 31 December 2006."
        )

    def test_the_point_in_time_phrase_takes_one_date_not_a_range(self, enacted):
        version = enacted.versions.get(version=0)
        text = _by_kind(enacted, version)[LEGAL]
        assert "as it appeared on" in text
        assert " to " not in text

    def test_an_unloaded_base_regulation_is_omitted_not_guessed(self, enacted):
        Regulation.objects.all().delete()
        version = enacted.versions.get(version=0)
        text = _by_kind(enacted, version)[LEGAL]
        # No instrument number rather than a wrong one: the base-enactment gap
        # is real, and a citation nobody can verify is worse than a short one.
        assert "O Reg" not in text
        assert text.startswith("Article 3.2.5.7.")


@pytest.mark.django_db
class TestMissingFactsAreDroppedNotInvented:
    def test_a_divisionless_provision_says_no_division(self, enacted):
        enacted.division = ""
        enacted.save(update_fields=["division"])
        version = enacted.versions.get(version=0)
        texts = _by_kind(enacted, version)
        assert "Division" not in texts[LEGAL]
        assert "Div." not in texts[REPORT]

    def test_an_untitled_version_drops_the_heading(self, enacted):
        version = enacted.versions.get(version=0)
        version.title = ""
        version.save(update_fields=["title"])
        text = _by_kind(enacted, version)[REPORT]
        assert "—" not in text
        assert "Article 3.2.5.7. (in force" in text

    def test_a_never_in_force_version_names_no_day(self, enacted):
        version = enacted.versions.get(version=0)
        # ``never_in_force`` is derived, not stored: a zero-duration window is
        # one, and it is the common shape (a base v0 superseded on the
        # edition's own start date).
        version.ineffective_date = version.effective_date
        version.save(update_fields=["ineffective_date"])
        texts = _by_kind(enacted, version)
        # "as it appeared on <date>" would claim the text stood on a day it
        # never did.
        assert "as it appeared on" not in texts[LEGAL]
        assert "never in force" in texts[LEGAL]
        assert "never in force" in texts[REPORT]
