"""Tests for per-page search-engine metadata on provision pages.

The property that matters most is agreement: the canonical URL a page declares
must be the URL the sitemap submits. A sitemap that submits v2 while v2
declares v3 canonical tells the crawler to ignore everything we gave it, and
nothing else in this module matters if that breaks.
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from django.conf import settings
from PIL import Image

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    CodeEditionProvisionVersionClause,
    Regulation,
    RegulationClause,
    User,
)
from core.seo import (
    DEFAULT_DESCRIPTION,
    DEFAULT_TITLE,
    SITE_NAME,
    SOCIAL_IMAGE_HEIGHT,
    SOCIAL_IMAGE_PATH,
    SOCIAL_IMAGE_WIDTH,
    amending_regulations,
    canonical_version_number,
    exhibit_title,
    last_governed_day,
    provision_jsonld,
    provision_page_meta,
    regulation_jsonld,
    temporal_coverage,
)
from core.sitemaps import ProvisionSitemap


class TestExhibitTitle:
    """A printable page's title is the name the saved file gets.

    The browser has no ``Content-Disposition`` to read on a print, so it
    builds the default name from ``document.title``. A title that keeps a
    character the filesystem rejects is a title the reader has to retype.
    """

    def test_drops_every_character_a_filename_cannot_hold(self):
        title = exhibit_title(
            'comparison A/B: "x" <y> | z * ? \\ w — v · u', date(2026, 8, 6)
        )
        assert not set(title) & set('\\/:*?"<>|—·')

    def test_states_the_retrieval_date(self):
        """Two exhibits of one provision months apart are different
        documents, and a folder holding both must say which is which."""
        assert exhibit_title("OBC 2006 3.2.5.7. v0", date(2026, 8, 6)).endswith(
            "retrieved 2026-08-06"
        )

    def test_leaves_the_provision_number_intact(self):
        """Dots are legal in a filename and they are the provision's
        identity — stripping them would be the one edit that loses the
        subject."""
        assert "3.2.5.7." in exhibit_title("OBC 2006 3.2.5.7. v0", date(2026, 8, 6))

    def test_does_not_spend_the_leading_words_on_the_site_name(self):
        """A filename is read in a folder listing, where the first words are
        the ones that sort and the ones a narrow column keeps. Every exhibit
        would share the site name, so it distinguishes nothing and pushes the
        subject out of view."""
        title = exhibit_title("OBC 2006 3.2.5.7. v0", date(2026, 8, 6))
        assert SITE_NAME not in title
        assert title.startswith("OBC 2006")

    def test_collapses_the_gaps_a_removal_leaves(self):
        assert "  " not in exhibit_title("OBC 2006 — 3.2.5.7.", date(2026, 8, 6))


class TestLastGovernedDay:
    """The one conversion three modules share.

    The stored window is half-open, so every surface that writes "to" means
    the day before the stored end.  The conversion was written three times,
    and one of the three printed the stored date — a page title that claimed
    a text applied on the first day it did not.
    """

    def test_it_names_the_day_before_the_stored_end(self):
        assert last_governed_day(date(2009, 1, 1)) == date(2008, 12, 31)

    def test_an_open_window_has_no_last_day(self):
        # Not today's date: the edition may have been superseded without this
        # provision changing, and "to today" claims a currency nobody checked.
        assert last_governed_day(None) is None


@pytest.fixture
def provision(db, settings):
    """One OBC 2006 provision with a three-version amendment chain."""
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006, effective_date=date(2006, 12, 31),
    )
    prov = CodeEditionProvision.objects.create(
        edition=edition, provision_id="3.2.5.7.", level="article", division="B",
    )
    windows = [
        (date(2006, 12, 31), date(2009, 1, 1)),
        (date(2009, 1, 1), date(2012, 1, 1)),
        (date(2012, 1, 1), None),
    ]
    for version, (start, end) in enumerate(windows):
        CodeEditionProvisionVersion.objects.create(
            provision=prov,
            version=version,
            effective_date=start,
            ineffective_date=end,
            title="Fire Department Access Routes",
            html="<p>text</p>",
        )
    return prov


@pytest.mark.django_db
class TestProvisionPageMeta:
    def test_title_names_provision_heading_edition_and_window(self, provision):
        version = provision.versions.get(version=0)
        meta = provision_page_meta(provision, version)
        title = meta["meta_title"]
        assert "3.2.5.7." in title
        assert "Fire Department Access Routes" in title
        assert "2006" in title
        # The stored end is 1 January 2009, the first day this text did *not*
        # apply.  The title names the last day it did.
        assert "in force 31 December 2006 to 31 December 2008" in title

    def test_description_fits_the_search_result_snippet(self, provision):
        version = provision.versions.get(version=0)
        description = provision_page_meta(provision, version)["meta_description"]
        assert len(description) <= 155
        assert "3.2.5.7." in description

    def test_an_open_window_says_from_and_never_claims_currency(self, provision):
        """A historical text must not be described as in force to today."""
        version = provision.versions.get(version=2)
        meta = provision_page_meta(provision, version)
        assert "in force from 1 January 2012" in meta["meta_title"]
        assert " to " not in meta["meta_title"]

    def test_the_title_and_the_json_ld_name_the_same_last_day(self, provision):
        """One window, two surfaces, one conversion.

        The prose window and ``temporalCoverage`` are built from the same
        half-open dates.  They disagreed for as long as each did its own
        arithmetic, so the property is that they cannot.
        """
        version = provision.versions.get(version=0)
        title = provision_page_meta(provision, version)["meta_title"]
        assert "31 December 2008" in title
        assert temporal_coverage(
            version.effective_date, version.ineffective_date
        ).endswith("/2008-12-31")

    def test_a_window_that_outlives_its_edition_keeps_its_own_end(self, provision):
        """CCM computes these dates, and a window may run past its edition.

        The contract extends the old version's end to the overlap end during a
        transition, and two editions' versions co-exist there on purpose.  To
        take the earlier of the two ends would delete the overlap and let two
        edition pages claim the same days.
        """
        edition = provision.edition
        edition.ineffective_date = date(2008, 1, 1)
        edition.save()
        version = provision.versions.get(version=0)  # ends 2009-01-01
        title = provision_page_meta(provision, version)["meta_title"]
        assert "in force 31 December 2006 to 31 December 2008" in title

    def test_a_version_that_governed_no_day_is_not_given_a_backwards_range(
        self, provision
    ):
        """A zero-duration window is a real link in the amendment chain.

        Subtracting the day would print "to" a date before "from", which reads
        as a data fault rather than as what it is.
        """
        version = provision.versions.get(version=1)
        version.ineffective_date = version.effective_date
        version.save()
        assert "never in force" in provision_page_meta(provision, version)["meta_title"]

    def test_an_untitled_version_still_produces_usable_metadata(self, provision):
        version = provision.versions.get(version=1)
        version.title = ""
        version.save()
        meta = provision_page_meta(provision, version)
        assert meta["meta_title"].startswith("3.2.5.7. — Ontario Building Code 2006")
        assert meta["meta_description"]

    def test_every_version_declares_the_highest_as_canonical(self, provision):
        assert canonical_version_number(provision) == 2
        for version in provision.versions.all():
            meta = provision_page_meta(provision, version)
            assert meta["canonical_path"] == "/provision/OBC_2006/B/3.2.5.7./v2/"

    def test_the_canonical_url_is_the_url_the_sitemap_submits(self, provision):
        """The rule lives in core.seo; core.sitemaps implements it set-based."""
        submitted = list(ProvisionSitemap().items())
        assert len(submitted) == 1
        sitemap_url = ProvisionSitemap().location(submitted[0])
        version = provision.versions.get(version=0)
        assert provision_page_meta(provision, version)["canonical_path"] == sitemap_url


@pytest.mark.django_db
class TestPermalinkPage:
    def test_the_page_emits_its_title_description_and_canonical(
        self, client, provision
    ):
        response = client.get("/provision/OBC_2006/B/3.2.5.7./v0/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "<title>3.2.5.7. Fire Department Access Routes" in body
        assert '<meta name="description" content="The text of Ontario Building Code' in body
        assert 'rel="canonical"' in body
        assert "/provision/OBC_2006/B/3.2.5.7./v2/" in body

    def test_other_pages_keep_the_default_description(self, client):
        body = client.get("/terms/").content.decode()
        assert f'<meta name="description" content="{DEFAULT_DESCRIPTION}">' in body


@pytest.mark.django_db
class TestSocialCard:
    """What a forwarded link shows.

    A link in an email or a chat message is rendered from these tags alone,
    so a page with none of them arrives as a bare URL and reads as broken.
    """

    def test_a_provision_page_carries_its_own_card(self, client, provision):
        body = client.get("/provision/OBC_2006/B/3.2.5.7./v0/").content.decode()
        assert '<meta property="og:type" content="article">' in body
        assert '<meta property="og:site_name" content="CodeChronicle">' in body
        assert '<meta name="twitter:card" content="summary_large_image">' in body
        assert (
            '<meta property="og:title" content="3.2.5.7. Fire Department Access '
            'Routes' in body
        )
        assert '<meta property="og:description" content="The text of Ontario' in body

    def test_the_card_title_drops_the_site_name_tail(self, provision):
        """The card prints the site name on its own line, so a headline that
        repeats it spends the one line a reader skims."""
        version = provision.versions.get(version=0)
        meta = provision_page_meta(provision, version)
        assert meta["meta_title"].endswith(" | CodeChronicle")
        assert not meta["social_title"].endswith(" | CodeChronicle")
        assert meta["meta_title"].startswith(meta["social_title"])

    def test_the_shared_url_is_the_canonical_one(self, client, provision):
        """A share of v0 must credit the page a share of v2 credits, for the
        reason the canonical link exists at all."""
        body = client.get("/provision/OBC_2006/B/3.2.5.7./v0/").content.decode()
        assert (
            '<meta property="og:url" content="http://testserver'
            '/provision/OBC_2006/B/3.2.5.7./v2/">' in body
        )

    def test_a_page_of_its_own_falls_back_to_the_site_card(self, client):
        body = client.get("/terms/").content.decode()
        assert '<meta property="og:type" content="website">' in body
        # The constant, not the sentence: the copy is the marketing team's to
        # change, and a test that pins the words fails on an edit that is
        # correct.  What must hold is that the page carries the site default.
        assert f'<meta property="og:title" content="{DEFAULT_TITLE}">' in body
        assert '<meta property="og:url" content="http://testserver/terms/">' in body

    def test_the_card_image_is_absolute_and_sized(self, client):
        """A crawler resolves neither a relative path nor an unknown size."""
        body = client.get("/terms/").content.decode()
        assert 'content="http://testserver/static/images/social-card.png">' in body
        assert f'"og:image:width" content="{SOCIAL_IMAGE_WIDTH}">' in body
        assert f'"og:image:height" content="{SOCIAL_IMAGE_HEIGHT}">' in body

    def test_the_declared_size_is_the_file_on_disk(self):
        """The tags and the PNG are produced by different code at different
        times — the command draws it, the template declares it.  A crawler
        told the wrong size reserves the wrong space, and nothing else in the
        suite would notice the two drifting apart."""
        path = Path(settings.STATICFILES_DIRS[0]) / SOCIAL_IMAGE_PATH
        assert path.exists(), f"the card is missing; run make_social_card ({path})"
        with Image.open(path) as card:
            assert card.size == (SOCIAL_IMAGE_WIDTH, SOCIAL_IMAGE_HEIGHT)

    def test_a_locked_page_carries_a_generic_card(self, client, provision, settings):
        """It names the edition, and it names no provision.

        A card that quoted the heading would promise a text the page does not
        deliver.  No card at all is worse still: the link arrives as a bare URL
        and reads as broken, which is the failure the card exists to prevent.

        ``og:url`` still carries the provision number, because it is the URL
        the reader pasted.  What must not appear is a claim about the text.
        """
        settings.FREE_TIER_CODE_NAMES = ["OBC_2012"]
        response = client.get("/provision/OBC_2006/B/3.2.5.7./v0/")
        assert response.status_code == 403
        assert "locked_edition.html" in [t.name for t in response.templates]
        body = response.content.decode()
        assert '<meta property="og:title" content="OBC 2006 is Pro content' in body
        assert '<meta name="twitter:card" content="summary_large_image">' in body
        # The heading is the promise, and it appears nowhere on the page.
        assert "Fire Department Access Routes" not in body
        for tag in ("og:title", "og:description", "twitter:title", "twitter:description"):
            content = re.search(rf'"{tag}" content="([^"]*)"', body)
            assert content is not None
            assert "3.2.5.7." not in content.group(1)

    def test_a_locked_page_keeps_its_own_tab_title(self, client, provision, settings):
        settings.FREE_TIER_CODE_NAMES = ["OBC_2012"]
        body = client.get("/provision/OBC_2006/B/3.2.5.7./v0/").content.decode()
        assert "<title>OBC 2006 — Pro content | CodeChronicle</title>" in body


@pytest.fixture
def enacted(provision):
    """The same provision, with the instruments behind it loaded.

    A base regulation on the edition, and one amending regulation whose clause
    produced v1.  v0 and v2 keep no contributing clause, which is the ordinary
    state: v0 was never amended, and CCM does not always ship the link.

    The edition is given an end date, because OBC 2006 has one.  Without it
    every currency assertion below tests a corpus that does not exist.

    ``reg_id`` holds the **bare** number, which is what CCM ships and what the
    loaded corpus holds.  It used to carry the "O. Reg." prefix here, and that
    single wrong character made the identifier assertions below assert nothing:
    they compared the block against a fixture that had already done the work
    the block was supposed to do, and production shipped "350/06" as a citation
    for weeks with the suite green.  Keep the fixture as CCM ships it.
    """
    edition = provision.edition
    edition.ineffective_date = date(2014, 1, 1)
    edition.save()
    base = Regulation.objects.create(
        reg_id="350/06",
        edition=edition,
        role=Regulation.Role.BASE,
        filed_date=date(2006, 8, 18),
        effective_date=date(2006, 12, 31),
        source_url="https://www.ontario.ca/laws/regulation/060350",
    )
    amending = Regulation.objects.create(
        reg_id="315/08",
        edition=edition,
        role=Regulation.Role.AMENDMENT,
        amends=base,
        filed_date=date(2008, 9, 10),
        effective_date=date(2009, 1, 1),
    )
    clause = RegulationClause.objects.create(regulation=amending, clause_id="1")
    CodeEditionProvisionVersionClause.objects.create(
        version=provision.versions.get(version=1), clause=clause, apply_order=0,
    )
    return provision


def _block(provision, version, **kwargs):
    """The emitted block, parsed back into a dict."""
    raw = provision_jsonld(
        provision, version, origin="https://www.codechronicle.ca", **kwargs
    )
    return json.loads(raw)


@pytest.mark.django_db
class TestProvisionJsonLd:
    """The machine-readable form of the in-force window.

    Nothing here changes what a reader sees.  What it must never do is state a
    date or a currency the page itself does not support: a wrong figure in
    prose is a bug, and a wrong figure in structured data is a bug an answer
    engine repeats with confidence.
    """

    def test_the_block_is_valid_json(self, enacted):
        block = _block(enacted, enacted.versions.get(version=0))
        assert block["@context"] == "https://schema.org"
        assert block["@type"] == "Legislation"

    def test_a_superseded_edition_is_not_in_force(self, enacted):
        """The error this product cannot afford, asserted directly."""
        for version in enacted.versions.all():
            block = _block(enacted, version)
            assert block["legislationLegalForce"] == "NotInForce"

    def test_a_current_edition_is_in_force(self, enacted):
        """The other half of the rule.  Without it an inverted computation
        still passes, because free scope today holds one superseded edition
        and nothing else — every page a crawler sees says NotInForce.
        """
        edition = enacted.edition
        edition.ineffective_date = None
        edition.save()
        version = enacted.versions.get(version=2)
        block = _block(enacted, version, today=date(2013, 6, 1))
        assert block["legislationLegalForce"] == "InForce"

    def test_the_edition_end_closes_a_version_with_no_end_of_its_own(self, enacted):
        """A few provisions outlive their edition and carry no ineffective_date.
        Read alone they look open-ended, and open-ended reads as current.
        """
        version = enacted.versions.get(version=2)
        assert version.ineffective_date is None
        block = _block(enacted, version, today=date(2020, 1, 1))
        assert block["legislationLegalForce"] == "NotInForce"
        assert block["temporalCoverage"] == "2012-01-01/2013-12-31"

    def test_the_edition_end_never_shortens_a_version_that_has_its_own(
        self, enacted
    ):
        """The edition end is a fallback for a null, not a ceiling.

        A version whose window runs past its edition is a transition overlap
        CCM emits on purpose.  Shortening it here would report a text as
        NotInForce on days it still governed.
        """
        version = enacted.versions.get(version=0)  # 2006-12-31 to 2009-01-01
        edition = enacted.edition
        edition.ineffective_date = date(2008, 1, 1)
        edition.save()
        block = _block(enacted, version, today=date(2008, 6, 1))
        assert block["temporalCoverage"] == "2006-12-31/2008-12-31"
        assert block["legislationLegalForce"] == "InForce"

    def test_coverage_ends_the_day_before_the_ineffective_date(self, enacted):
        """The stored window is half-open; an ISO interval is closed.  Copying
        ineffective_date across claims the text applied on the day it stopped.
        """
        version = enacted.versions.get(version=0)
        assert version.ineffective_date == date(2009, 1, 1)
        assert _block(enacted, version)["temporalCoverage"] == "2006-12-31/2008-12-31"

    def test_an_open_window_uses_the_open_form_not_today(self, enacted):
        edition = enacted.edition
        edition.ineffective_date = None
        edition.save()
        version = enacted.versions.get(version=2)
        assert _block(enacted, version)["temporalCoverage"] == "2012-01-01/.."

    def test_a_version_that_never_governed_a_day_claims_no_window(self, enacted):
        version = enacted.versions.get(version=1)
        version.ineffective_date = version.effective_date
        version.save()
        block = _block(enacted, version)
        assert version.never_in_force
        assert "temporalCoverage" not in block
        assert block["legislationLegalForce"] == "NotInForce"

    def test_the_two_dates_are_not_the_same_date(self, enacted):
        """legislationDate is when the instrument was adopted;
        legislationDateVersion is when this version began.  Collapsing them
        back-dates every amendment to the edition's own date.
        """
        version = enacted.versions.get(version=1)
        block = _block(enacted, version)
        assert block["legislationDate"] == "2006-08-18"
        assert block["legislationDateVersion"] == "2009-01-01"

    def test_the_url_is_canonical_not_the_page_being_rendered(self, enacted):
        for version in enacted.versions.all():
            block = _block(enacted, version)
            assert block["url"] == (
                "https://www.codechronicle.ca/provision/OBC_2006/B/3.2.5.7./v2/"
            )

    def test_the_base_regulation_is_named_on_every_version(self, enacted):
        """An edition-level fact, so it survives the base-enactment gap."""
        for version in enacted.versions.all():
            consolidates = _block(enacted, version)["legislationConsolidates"]
            assert consolidates["legislationIdentifier"] == "O. Reg. 350/06"
            assert consolidates["sameAs"].startswith("https://www.ontario.ca/")

    def test_no_version_claims_an_amender_the_vocabulary_cannot_express(
        self, enacted
    ):
        """schema.org defines no inverse of ``legislationChanges``.

        Every change relation it defines runs from the instrument to the text
        it acts on, so a provision — which is the subject of its own page —
        cannot name what amended it.  The block used to emit
        ``legislationChangedBy``, which the Schema Markup Validator rejects as
        INVALID_PREDICATE.  A property outside the vocabulary is not a partial
        win: a strict consumer drops the triple and a lenient one invents a
        term, so the edge was never communicated either way.

        Asserted on v1, the version an amending regulation really produced, so
        that a future attempt to state the edge from this side has to come back
        and read the reason first.
        """
        for version in enacted.versions.all():
            assert "legislationChangedBy" not in _block(enacted, version)
        assert amending_regulations(enacted.versions.get(version=1))

    def test_the_amending_regulation_is_named_on_its_own_page(self, enacted):
        """The edge survives — with the instrument as its subject, which is the
        only direction schema.org offers."""
        amending = Regulation.objects.get(reg_id="315/08")
        block = json.loads(regulation_jsonld(amending, origin="https://x.test"))
        assert block["legislationChanges"]["legislationIdentifier"] == "O. Reg. 350/06"

    def test_the_identifier_is_a_citation_that_stands_alone(self, enacted):
        """The bare provision number names a provision in three editions and in
        more than one division, so on its own it identifies nothing.
        """
        block = _block(enacted, enacted.versions.get(version=0))
        assert block["legislationIdentifier"] == (
            "Article 3.2.5.7. of Division B of O. Reg. 350/06"
        )

    def test_an_untitled_version_omits_the_name(self, enacted):
        version = enacted.versions.get(version=0)
        version.title = ""
        version.save()
        block = _block(enacted, version)
        assert "name" not in block
        assert block["legislationIdentifier"]

    def test_a_heading_cannot_close_the_script_element(self, enacted):
        """json.dumps does not escape these three, and a heading is data we did
        not write.  An unescaped closing script tag ends the block early and
        drops the rest of the head into the body.
        """
        version = enacted.versions.get(version=0)
        version.title = "Routes </script><img src=x> & <b>more</b>"
        version.save()
        raw = provision_jsonld(enacted, version, origin="https://example.com")
        assert "<" not in raw
        assert ">" not in raw
        assert "&" not in raw
        assert json.loads(raw)["name"] == version.title


@pytest.mark.django_db
class TestJsonLdOnThePage:
    def test_a_provision_page_carries_the_block(self, client, enacted):
        body = client.get("/provision/OBC_2006/B/3.2.5.7./v0/").content.decode()
        found = re.search(
            r'<script type="application/ld\+json">(.*?)</script>', body, re.DOTALL
        )
        assert found is not None
        block = json.loads(found.group(1))
        assert block["@type"] == "Legislation"
        assert block["url"] == "http://testserver/provision/OBC_2006/B/3.2.5.7./v2/"

    def test_a_locked_page_carries_no_block(self, client, enacted, settings):
        """The teaser is a 403 about an edition, not a page about a provision.
        No tier test achieves this — the view renders a template that sets
        nothing, and base.html prints the block only where it is set.
        """
        settings.FREE_TIER_CODE_NAMES = ["OBC_2012"]
        response = client.get("/provision/OBC_2006/B/3.2.5.7./v0/")
        assert response.status_code == 403
        assert "application/ld+json" not in response.content.decode()

    def test_a_page_with_no_subject_carries_no_block(self, client):
        assert "application/ld+json" not in client.get("/terms/").content.decode()


@pytest.mark.django_db
class TestTheIntervalAgreesWithTheVisibleWindow:
    """The machine's window and the reader's window, off the same responses.

    ``TestProvisionJsonLd`` proves the interval against the stored dates, and
    ``test_the_title_and_the_json_ld_name_the_same_last_day`` proves it against
    the page title.  Both of those compare two ``core.seo`` outputs, so a
    conversion that moved *inside* ``core.seo`` keeps them agreeing while the
    page disagrees with itself.

    The window a reader sees on the exhibit does not come from ``core.seo``.
    It comes from :func:`core.citations.in_force_phrase`, and CLAUDE.md records
    that three private copies of the half-open conversion once gave three
    answers.  So these fetch the pages and compare the two modules' work as
    rendered.
    """

    URL = "/provision/OBC_2006/B/3.2.5.7./v0/"

    def _interval(self, client):
        body = client.get(self.URL).content.decode()
        found = re.search(
            r'<script type="application/ld\+json">(.*?)</script>', body, re.DOTALL
        )
        assert found is not None
        return json.loads(found.group(1))["temporalCoverage"]

    def _exhibit_window(self, client):
        """The phrase under the exhibit's "In force" label, and only that.

        Read out of its own ``<dd>`` rather than searched for in the body: the
        page also carries a ``core.seo`` window in a meta tag, and a loose
        search finds that one and reports agreement with itself.
        """
        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")
        printed = client.get(f"{self.URL}print/").content.decode()
        found = re.search(r">In force</dt>\s*<dd[^>]*>(.*?)</dd>", printed, re.DOTALL)
        assert found is not None
        return found.group(1).strip()

    def test_the_interval_ends_on_the_day_the_exhibit_says_it_does(
        self, client, enacted
    ):
        interval = self._interval(client)
        assert interval == "2006-12-31/2008-12-31"

        # The same last day, in the two spellings the two modules use.  Built
        # from the interval rather than written out, so the assertion cannot
        # drift from what the block actually said.
        last = date.fromisoformat(interval.split("/")[1])
        assert self._exhibit_window(client) == (
            f"in force 31 December 2006 to {last.day} December {last.year}"
        )

    def test_neither_surface_names_the_stored_end_date(self, client, enacted):
        """The off-by-one, asserted as an absence on both surfaces at once.

        1 January 2009 is the first day this text did *not* apply.  It is the
        value in the database, so it is what a fresh copy of the conversion
        prints, and it must appear on neither page.
        """
        assert "2009-01-01" not in self._interval(client)

        User.objects.create_user(email="r@example.com", password="testpass")
        client.login(email="r@example.com", password="testpass")
        printed = client.get(f"{self.URL}print/").content.decode()
        assert "to 1 January 2009" not in printed


@pytest.mark.django_db
class TestRegulationJsonLd:
    """The companion block on the regulation page.

    A provision's block names its base regulation and links here, so the
    object it names must describe itself when a crawler follows the link.
    """

    def _block(self, reg):
        return json.loads(
            regulation_jsonld(reg, origin="https://www.codechronicle.ca")
        )

    def test_the_block_names_the_instrument(self, enacted):
        base = Regulation.objects.get(reg_id="350/06")
        block = self._block(base)
        assert block["@type"] == "Legislation"
        assert block["legislationIdentifier"] == "O. Reg. 350/06"
        assert block["legislationType"] == "Regulation"
        assert block["legislationDate"] == "2006-08-18"
        assert block["sameAs"] == "https://www.ontario.ca/laws/regulation/060350"

    def test_the_url_matches_the_one_the_provision_block_links_to(self, enacted):
        """One node builder, because the two blocks point at each other."""
        base = Regulation.objects.get(reg_id="350/06")
        linked = _block(enacted, enacted.versions.get(version=0))[
            "legislationConsolidates"
        ]["url"]
        assert self._block(base)["url"] == linked

    def test_an_amending_regulation_names_what_it_changes(self, enacted):
        amending = Regulation.objects.get(reg_id="315/08")
        changes = self._block(amending)["legislationChanges"]
        assert changes["legislationIdentifier"] == "O. Reg. 350/06"

    def test_a_base_regulation_changes_nothing(self, enacted):
        base = Regulation.objects.get(reg_id="350/06")
        assert "legislationChanges" not in self._block(base)

    def test_an_instrument_claims_no_currency(self, enacted):
        """An amendment is not superseded the way a text is — the change it
        made stays made.  To state a window or a force here invents a fact.
        """
        for reg in Regulation.objects.all():
            block = self._block(reg)
            assert "temporalCoverage" not in block
            assert "legislationLegalForce" not in block

    def test_a_regulation_page_carries_the_block(self, client, enacted):
        base = Regulation.objects.get(reg_id="350/06")
        body = client.get(f"/regulation/{base.pk}/").content.decode()
        found = re.search(
            r'<script type="application/ld\+json">(.*?)</script>', body, re.DOTALL
        )
        assert found is not None
        assert json.loads(found.group(1))["legislationIdentifier"] == "O. Reg. 350/06"

    def test_a_locked_regulation_page_carries_no_block(
        self, client, enacted, settings
    ):
        settings.FREE_TIER_CODE_NAMES = ["OBC_2012"]
        base = Regulation.objects.get(reg_id="350/06")
        response = client.get(f"/regulation/{base.pk}/")
        assert response.status_code == 403
        assert "application/ld+json" not in response.content.decode()
