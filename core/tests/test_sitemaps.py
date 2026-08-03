"""Tests for /robots.txt and the sitemaps.

The property that matters is scope: the sitemap must list only what an
anonymous visitor can actually read.  Listing a Pro-only permalink invites a
crawler to index the locked-edition teaser under a provision's title, which is
both useless to the reader and a promise the page does not keep.
"""

from datetime import date

import pytest
from django.test import override_settings

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
)
from core.sitemaps import ProvisionSitemap, free_tier_edition_ids


@pytest.fixture
def obc_2006_edition(db, settings):
    """OBC 2006 with two provisions, one of which has three versions."""
    settings.FREE_TIER_CODE_NAMES = ["OBC_2006"]
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    edition = CodeEdition.objects.create(
        code=code, edition_id="2006", year=2006, effective_date=date(2006, 12, 31),
    )
    for provision_id, version_count in (("1.1.1.1.", 3), ("1.1.1.2.", 1)):
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id=provision_id, level="article", division="B",
        )
        for version in range(version_count):
            CodeEditionProvisionVersion.objects.create(
                provision=provision,
                version=version,
                effective_date=date(2007 + version, 1, 1),
                title="Scope",
                html="<p>Scope text</p>",
            )
    return edition


@pytest.mark.django_db
class TestRobots:
    def test_serves_plain_text_with_an_absolute_sitemap_link(self, client):
        response = client.get("/robots.txt")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")
        body = response.content.decode()
        assert "Sitemap: http://testserver/sitemap.xml" in body

    def test_disallows_the_private_surfaces(self, client):
        body = client.get("/robots.txt").content.decode()
        for path in ("/accounts/", "/admin/", "/history/", "/insights/", "/viewer/"):
            assert f"Disallow: {path}" in body


@pytest.mark.django_db
class TestSitemap:
    def test_index_lists_both_sections(self, client):
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        body = response.content.decode()
        assert "sitemap-pages.xml" in body
        assert "sitemap-provisions.xml" in body

    def test_pages_section_lists_about_not_the_redirecting_root(self, client):
        body = client.get("/sitemap-pages.xml").content.decode()
        assert "/about/" in body
        assert "/pricing/" in body

    def test_free_tier_edition_ids_resolves_names_to_pks(self, obc_2006_edition):
        assert obc_2006_edition.pk in free_tier_edition_ids()

    @override_settings(FREE_TIER_CODE_NAMES=[])
    def test_no_free_editions_means_no_provision_urls(self, obc_2006_edition):
        assert list(ProvisionSitemap().items()) == []

    def test_one_url_per_provision_not_per_version(self, obc_2006_edition):
        """Each provision contributes its final version and no other."""
        items = list(ProvisionSitemap().items())
        provision_ids = [item.provision_id for item in items]
        assert len(provision_ids) == len(set(provision_ids))
        # The three-version provision contributes v2, its final text.
        by_provision = {item.provision.provision_id: item.version for item in items}
        assert by_provision == {"1.1.1.1.": 2, "1.1.1.2.": 0}

    def test_location_and_lastmod_describe_the_chosen_version(self, obc_2006_edition):
        sitemap = ProvisionSitemap()
        final = next(i for i in sitemap.items() if i.provision.provision_id == "1.1.1.1.")
        assert sitemap.location(final) == "/provision/OBC_2006/B/1.1.1.1./v2/"
        assert sitemap.lastmod(final) == date(2009, 1, 1)


@pytest.mark.django_db
class TestProvisionSectionRenders:
    """The section as a crawler receives it.

    Every test above calls the sitemap's methods directly, so all of them
    passed while ``/sitemap-provisions.xml`` returned 500 in production: the
    worker ran out of memory building the page.  Rendering the real URL is the
    only check that sees that.
    """

    def test_the_section_renders_the_provision_urls(self, client, obc_2006_edition):
        response = client.get("/sitemap-provisions.xml")
        assert response.status_code == 200
        body = response.content.decode()
        assert "/provision/OBC_2006/B/1.1.1.1./v2/" in body
        assert "/provision/OBC_2006/B/1.1.1.2./v0/" in body

    def test_the_row_count_does_not_drive_the_query_count(
        self, client, obc_2006_edition, django_assert_max_num_queries
    ):
        """``location`` reads ``edition.code_name``, which reads ``code.code``.

        With the join stopping at the edition that is one query per provision,
        which is what killed the worker at corpus scale.  The bound is a
        constant so a regression shows up as a failure here rather than as a
        500 nobody sees.  The fixture holds two provisions and the section
        renders in five queries, so the N+1 makes seven and trips this.
        """
        with django_assert_max_num_queries(6):
            client.get("/sitemap-provisions.xml")

    def test_the_provision_text_is_never_loaded(self, obc_2006_edition):
        """A version row carries the whole provision text, and the sitemap
        holds a page of rows at once.  Six short columns are all it needs."""
        item = next(iter(ProvisionSitemap().items()))
        assert "html" in item.get_deferred_fields()
