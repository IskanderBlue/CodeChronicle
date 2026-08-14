"""XML sitemaps for the public, crawlable surface.

Only free-tier content is listed.  A sitemap is a claim that the URL returns
content to an anonymous visitor; a Pro-only permalink returns the locked-edition
teaser instead, so listing one invites the crawler to index an upsell page under
a provision's title.  The scope therefore comes from :mod:`core.access` — the
same helper the views gate on — rather than a second hand-kept list.

One URL per provision, not one per version.  A provision's amendment chain is
many near-identical texts; submitting all of them asks the crawler to choose a
canonical page for us, and it chooses badly.  ``ProvisionSitemap`` submits the
*final* version of each provision (the highest ``version`` number, which is how
the provision read when its edition was superseded) and lets the other versions
stay reachable — and indexable — through the on-page lineage links.
"""

from datetime import date
from typing import Any

from django.contrib.sitemaps import Sitemap
from django.db.models import QuerySet
from django.urls import reverse

from core.access import free_tier_code_names
from core.models import CodeEdition, CodeEditionProvisionVersion
from core.permalinks import provision_permalink_url


def free_tier_edition_ids() -> list[int]:
    """The primary keys of the editions in free scope.

    ``CodeEdition.code_name`` is a Python property (``code.code`` + ``_`` +
    ``edition_id``), not a column, so the tier set cannot be pushed into a
    single ``filter(...)``.  Resolving the names to pks once, here, keeps
    ``core.access`` the only definition of a tier while still letting the
    provision query filter in the database instead of in Python — which matters
    at sitemap scale (thousands of rows) in a way it does not on the landing
    page.
    """
    names = free_tier_code_names()
    return [
        e.pk
        for e in CodeEdition.objects.select_related("code").only(
            "edition_id", "code__code"
        )
        if e.code_name in names
    ]

#: Pages that describe the product rather than the corpus.  ``core:about`` is
#: listed instead of ``core:landing`` because the two render the same view and
#: ``/`` redirects a signed-in reader away; ``/about/`` is the stable address of
#: the explanation.  ``core:search`` is the tool itself — thin for a crawler,
#: but it is the page a brand-name search should land on.
STATIC_PAGE_NAMES: tuple[str, ...] = (
    "core:about",
    "core:search",
    "core:pricing",
    "core:data_sources",
    "core:verification_guide",
    "core:list_punctuation",
    "core:guard_height",
    "core:terms_of_service",
    "core:privacy_policy",
)


class StaticViewSitemap(Sitemap):
    """The hand-written pages: what the product is, what it covers, terms."""

    changefreq = "monthly"
    priority = 0.6
    protocol = "https"

    def items(self) -> tuple[str, ...]:
        return STATIC_PAGE_NAMES

    def location(self, item: str) -> str:
        return reverse(item)


class ProvisionSitemap(Sitemap):
    """Every free-tier provision, at its final version.

    This is the corpus half of the sitemap and the reason the file exists: each
    row is a page answering "what did this provision say, and when", which is a
    question no general search engine can currently answer for a superseded
    Ontario edition.
    """

    changefreq = "yearly"
    priority = 0.8
    protocol = "https"
    limit = 5000

    def items(self) -> QuerySet[CodeEditionProvisionVersion]:
        # DISTINCT ON (provision) with a matching leading ORDER BY is the
        # Postgres way to take one row per group without a correlated subquery;
        # the ordering picks the highest version within each provision.
        #
        # Two things here are load-bearing on a one-gigabyte host, and the
        # sitemap returned 500 without them because the worker was killed:
        #
        # * ``code`` must be joined as well as ``edition``.  ``location`` reads
        #   ``edition.code_name``, which reads ``code.code``, so stopping the
        #   join at the edition costs one query per provision.
        # * ``only`` must exclude ``html``.  A version row carries the whole
        #   provision text, and a sitemap page holds ``limit`` rows in memory
        #   at once.  The sitemap needs six short columns and none of the text.
        return (
            CodeEditionProvisionVersion.objects
            .filter(provision__edition_id__in=free_tier_edition_ids())
            .select_related("provision", "provision__edition", "provision__edition__code")
            .only(
                "version",
                "effective_date",
                "provision__division",
                "provision__provision_id",
                "provision__edition__edition_id",
                "provision__edition__code__code",
            )
            .order_by("provision_id", "-version")
            .distinct("provision_id")
        )

    def location(self, item: CodeEditionProvisionVersion) -> str:
        provision = item.provision
        return provision_permalink_url(
            provision.edition.code_name,
            provision.division,
            provision.provision_id,
            item.version,
        )

    def lastmod(self, item: CodeEditionProvisionVersion) -> date | None:
        # The date the text started to read this way.  A superseded edition's
        # provisions genuinely never change again, which is exactly what we
        # want a crawler to learn.
        return item.effective_date


#: Handed to ``django.contrib.sitemaps.views.sitemap`` in the URLconf.
SITEMAPS: dict[str, Any] = {
    "pages": StaticViewSitemap,
    "provisions": ProvisionSitemap,
}
