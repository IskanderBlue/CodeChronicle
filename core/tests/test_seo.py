"""Tests for per-page search-engine metadata on provision pages.

The property that matters most is agreement: the canonical URL a page declares
must be the URL the sitemap submits. A sitemap that submits v2 while v2
declares v3 canonical tells the crawler to ignore everything we gave it, and
nothing else in this module matters if that breaks.
"""

from datetime import date

import pytest

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
)
from core.seo import canonical_version_number, provision_page_meta
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
        body = client.get("/pricing/").content.decode()
        assert '<meta name="description" content="Search the Ontario Building Code' in body
