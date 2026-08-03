"""Tests for per-page search-engine metadata on provision pages.

The property that matters most is agreement: the canonical URL a page declares
must be the URL the sitemap submits. A sitemap that submits v2 while v2
declares v3 canonical tells the crawler to ignore everything we gave it, and
nothing else in this module matters if that breaks.
"""

import re
from datetime import date

import pytest

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
)
from core.seo import (
    DEFAULT_DESCRIPTION,
    DEFAULT_TITLE,
    canonical_version_number,
    provision_page_meta,
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
        assert '<meta property="og:image:width" content="1200">' in body
        assert '<meta property="og:image:height" content="630">' in body

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
