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
)
from core.seo import (
    DEFAULT_DESCRIPTION,
    DEFAULT_TITLE,
    SOCIAL_IMAGE_HEIGHT,
    SOCIAL_IMAGE_PATH,
    SOCIAL_IMAGE_WIDTH,
    canonical_version_number,
    provision_jsonld,
    provision_page_meta,
    regulation_jsonld,
)
from core.sitemaps import ProvisionSitemap


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
        assert "in force 31 December 2006 to 1 January 2009" in title

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
    """
    edition = provision.edition
    edition.ineffective_date = date(2014, 1, 1)
    edition.save()
    base = Regulation.objects.create(
        reg_id="O. Reg. 350/06",
        edition=edition,
        role=Regulation.Role.BASE,
        filed_date=date(2006, 8, 18),
        effective_date=date(2006, 12, 31),
        source_url="https://www.ontario.ca/laws/regulation/060350",
    )
    amending = Regulation.objects.create(
        reg_id="O. Reg. 315/08",
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

    def test_the_amending_regulation_is_named_only_where_it_applies(self, enacted):
        """Absent on a version nothing amended, rather than falling back to the
        base regulation — a guessed citation is a false one.
        """
        assert "legislationChangedBy" not in _block(
            enacted, enacted.versions.get(version=0)
        )
        changed_by = _block(enacted, enacted.versions.get(version=1))[
            "legislationChangedBy"
        ]
        assert [r["legislationIdentifier"] for r in changed_by] == ["O. Reg. 315/08"]

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
        base = Regulation.objects.get(reg_id="O. Reg. 350/06")
        block = self._block(base)
        assert block["@type"] == "Legislation"
        assert block["legislationIdentifier"] == "O. Reg. 350/06"
        assert block["legislationType"] == "Regulation"
        assert block["legislationDate"] == "2006-08-18"
        assert block["sameAs"] == "https://www.ontario.ca/laws/regulation/060350"

    def test_the_url_matches_the_one_the_provision_block_links_to(self, enacted):
        """One node builder, because the two blocks point at each other."""
        base = Regulation.objects.get(reg_id="O. Reg. 350/06")
        linked = _block(enacted, enacted.versions.get(version=0))[
            "legislationConsolidates"
        ]["url"]
        assert self._block(base)["url"] == linked

    def test_an_amending_regulation_names_what_it_changes(self, enacted):
        amending = Regulation.objects.get(reg_id="O. Reg. 315/08")
        changes = self._block(amending)["legislationChanges"]
        assert changes["legislationIdentifier"] == "O. Reg. 350/06"

    def test_a_base_regulation_changes_nothing(self, enacted):
        base = Regulation.objects.get(reg_id="O. Reg. 350/06")
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
        base = Regulation.objects.get(reg_id="O. Reg. 350/06")
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
        base = Regulation.objects.get(reg_id="O. Reg. 350/06")
        response = client.get(f"/regulation/{base.pk}/")
        assert response.status_code == 403
        assert "application/ld+json" not in response.content.decode()
