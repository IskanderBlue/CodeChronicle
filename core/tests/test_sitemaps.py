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

    def test_disallows_the_exhibits(self, client):
        """Every provision links its own print route, and every fetch of one
        by an anonymous crawler is a login redirect carrying nothing."""
        body = client.get("/robots.txt").content.decode()
        assert "Disallow: /provision/*/print/" in body
        assert "Disallow: /compare/print/" in body

    def test_the_comparison_page_stays_indexable(self, client):
        """Pinned, because "compare looks expensive" is an easy wrong call.

        The reachable set is bounded — links are order-normalised and only
        join versions of one provision plus one lineage hop — and a comparison
        renders two versions rather than a subtree, so it is cheaper than the
        average permalink.  It is also the only page that answers what changed
        between two versions.
        """
        body = client.get("/robots.txt").content.decode()
        assert "Disallow: /compare/\n" not in body

    def test_the_costly_rules_sit_in_the_wildcard_group(self, client):
        """They must precede the first named agent, or they bind to nobody.

        A rule after a ``User-agent:`` line belongs to that agent's group.
        Putting these below the named crawlers would silently exempt every
        crawler that matters.
        """
        body = client.get("/robots.txt").content.decode()
        first_named = body.index("User-agent: MJ12bot")
        assert body.index("Disallow: /compare/print/") < first_named
        assert body.index("Disallow: /provision/*/print/") < first_named

    def test_refuses_the_backlink_crawlers(self, client):
        body = client.get("/robots.txt").content.decode()
        for agent in ("MJ12bot", "SemrushBot", "AhrefsBot"):
            assert f"User-agent: {agent}" in body

    def test_the_search_and_ai_crawlers_are_still_welcome(self, client):
        """Googlebot brings readers; the AI answer engines may yet.

        Pinned because refusing them is a product decision, not a cost one,
        and it should not arrive as a side effect of tidying this file.
        """
        body = client.get("/robots.txt").content.decode()
        for agent in ("Googlebot", "GPTBot", "ClaudeBot", "PerplexityBot"):
            assert f"User-agent: {agent}" not in body


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
