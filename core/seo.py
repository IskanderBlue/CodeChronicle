"""Page-level search-engine metadata for provision pages.

Three thousand provision pages that share one title and one description look
interchangeable to a search engine, and a page that looks interchangeable does
not rank. This module gives each one a title and a description drawn from the
provision itself — its number, its heading, its edition, and the dates it was
in force.

It also owns the **canonical-version rule**, which the sitemap and the page
must agree on or the whole exercise backfires:

    The canonical page for a provision is its HIGHEST version number.

A provision's amendment chain is many near-identical texts at many URLs. Left
alone, a search engine treats them as duplicates and splits the chain's
ranking across them. Naming one canonical concentrates it. The highest version
is chosen because it is how the provision read when its edition was superseded
— the last thing the legislature said on the subject in that edition — and
because it is a rule that needs no query date to evaluate.

``core.sitemaps`` implements the same rule set-based (``DISTINCT ON`` ordered
by descending version). Change one and you must change the other; a sitemap
that submits v2 while v2 declares v3 canonical asks the crawler to ignore
every URL we gave it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Max

from config.code_metadata import get_code_display_name
from core.models import CodeEditionProvision, CodeEditionProvisionVersion
from core.permalinks import provision_permalink_url

#: Longest description we emit. Search engines truncate around 155-160
#: characters; a sentence cut mid-word in the results page reads as neglect.
MAX_DESCRIPTION = 155

#: The name of this site, as a social card prints it.
SITE_NAME = "CodeChronicle"

#: What every page title ends with. Stripped from the social title, because a
#: card already prints the site name on its own line and a headline that
#: repeats it wastes the only line a reader skims.
TITLE_SUFFIX = f" | {SITE_NAME}"

#: The title and description a page carries when it says nothing of its own.
#: Both the ``<title>`` and the social card read them, so a page cannot
#: describe itself one way to a reader and another way to a crawler.
DEFAULT_TITLE = "CodeChronicle — the Ontario Building Code, dated, sourced, and searchable"
DEFAULT_DESCRIPTION = (
    "Search the Ontario Building Code as it read in the past, with "
    "the amendment history and the regulation behind every change."
)

#: The static social card, 1200x630. A path, never a resolved URL: the
#: manifest does not exist during CI ``check`` or the entrypoint ``migrate``,
#: so ``{% static %}`` must run at request time (``project_static_url_import_time``).
SOCIAL_IMAGE_PATH = "images/social-card.png"
SOCIAL_IMAGE_ALT = DEFAULT_TITLE

#: The card's real pixel size, declared in the tags so a crawler reserves the
#: right space.  2:1 is the one ratio every platform renders whole: Slack,
#: LinkedIn and Mail scale a card to the message width and keep its ratio,
#: while X normalises toward 2:1 and crops anything wider.
#:
#: ``make_social_card`` draws into this frame and refuses to write a card that
#: disagrees with these numbers, rather than let the tags lie.
SOCIAL_IMAGE_WIDTH = 1200
SOCIAL_IMAGE_HEIGHT = 600


def canonical_version_number(provision: CodeEditionProvision) -> int | None:
    """The version this provision's pages should point at. See module docstring."""
    return CodeEditionProvisionVersion.objects.filter(provision=provision).aggregate(
        top=Max("version")
    )["top"]


def _date_phrase(effective: date | None, ineffective: date | None) -> str:
    """How long this version stood, in prose.

    An open-ended window says "from", not "to today": the edition may have been
    superseded without this provision changing, and claiming currency for a
    historical text is the one error this product cannot afford.
    """
    if effective is None:
        return ""
    start = effective.strftime("%d %B %Y").lstrip("0")
    if ineffective is None:
        return f"in force from {start}"
    end = ineffective.strftime("%d %B %Y").lstrip("0")
    return f"in force {start} to {end}"


def _truncate(text: str, limit: int = MAX_DESCRIPTION) -> str:
    """Cut at a word boundary and mark the cut."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return f"{cut}…"


def provision_page_meta(
    provision: CodeEditionProvision,
    version: CodeEditionProvisionVersion,
) -> dict[str, Any]:
    """Title, description and canonical URL for one provision-version page.

    The title leads with the provision number and heading because that is what
    a reader searches for, and ends with the edition and the in-force window
    because that is what distinguishes this page from the same provision in
    three other editions.
    """
    edition = provision.edition
    code_label = f"{get_code_display_name(edition.code.code)} {edition.edition_id}".strip()
    heading = (version.title or "").strip()
    dates = _date_phrase(version.effective_date, version.ineffective_date)

    title_parts = [provision.provision_id]
    if heading:
        title_parts.append(heading)
    title = f"{' '.join(title_parts)} — {code_label}"
    if dates:
        title = f"{title} ({dates})"

    subject = f"{code_label} {provision.provision_id}"
    if heading:
        subject = f"{subject}, {heading},"
    description = _truncate(
        f"The text of {subject} as it read"
        + (f" {dates}" if dates else "")
        + ", with the amendment history and the regulation behind each change."
    )

    canonical_version = canonical_version_number(provision)
    canonical_path = (
        provision_permalink_url(
            edition.code_name,
            provision.division,
            provision.provision_id,
            canonical_version,
        )
        if canonical_version is not None
        else ""
    )

    return {
        "meta_title": f"{title}{TITLE_SUFFIX}",
        # The same title without the site-name tail.  A card prints the site
        # name on its own line already, so the tail would say it twice and
        # eat the headline.  Derived from one string, not written again.
        "social_title": title,
        "meta_description": description,
        "canonical_path": canonical_path,
        # A provision page is a document with a subject and a date, not a
        # site section, so a card should announce it as one.
        "og_type": "article",
    }
