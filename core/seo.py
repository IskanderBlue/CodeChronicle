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

Finally it builds the ``schema.org/Legislation`` block each provision page
carries — the machine-readable form of the in-force window. See
``provision_jsonld``.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from django.db.models import Max
from django.http import HttpRequest
from django.urls import reverse
from django.utils.safestring import SafeString, mark_safe

from config.code_metadata import get_code_display_name
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    Regulation,
)
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


def site_origin(request: HttpRequest) -> str:
    """Scheme + host, for making a path absolute.

    The canonical link, ``og:url`` and the JSON-LD block all need it, and a
    crawler resolves none of them against the page it is reading.  One
    function so the three cannot disagree about the host.
    """
    return f"{request.scheme}://{request.get_host()}"


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


# ─────────────────────────────────────────────────────────────────────────
# schema.org/Legislation
#
# An invisible block in the page head.  It changes nothing a reader sees, and
# Google draws no rich result for the Legislation type today, so this will not
# make the listing look different.  What it does is state the in-force window
# in a form a crawler and an answer engine can act on — the one thing this
# product sells, and the one thing no other property on the page expresses
# mechanically.
#
# It is built here, beside ``provision_page_meta``, so the block and the
# metadata read the same objects and cannot disagree.  Never assemble it in a
# template: one apostrophe in a heading breaks the JSON silently.
#
# Nothing in here is guessed.  A value that cannot be sourced is omitted, and
# a wrong date carries further than a missing one once it is machine-readable.
# ─────────────────────────────────────────────────────────────────────────

#: Wikidata items for the jurisdictions whose codes are loaded, keyed by
#: ``Code.code``.  A map rather than a constant, because the value is a fact
#: about the jurisdiction and not about this deployment: when the first
#: national or out-of-province edition loads, an unlisted code omits the
#: property rather than silently inheriting Ontario's.
JURISDICTION_URIS = {
    "OBC": "https://www.wikidata.org/wiki/Q1904",  # Ontario
}

#: ``json.dumps`` does not escape these three, and a heading containing
#: "</script>" would end the block early and drop the rest of the page's head
#: into the body.  Django's ``json_script`` makes exactly these substitutions;
#: it hard-codes ``type="application/json"``, so the mapping is copied here
#: rather than the helper.
_SCRIPT_ESCAPES = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}


def effective_window(
    version: CodeEditionProvisionVersion, edition: CodeEdition
) -> tuple[date, date | None]:
    """The days this version actually governed, half-open ``[start, end)``.

    The version's own ``ineffective_date`` is not the whole story.  A few
    provisions outlive their edition and carry no end date at all, so reading
    the version alone reports a 2006 text as open-ended — which reads as
    current.  The edition's end closes it.  Whichever end comes first wins;
    ``None`` means genuinely open.
    """
    ends = [d for d in (version.ineffective_date, edition.ineffective_date) if d]
    return version.effective_date, min(ends) if ends else None


def legal_force(
    version: CodeEditionProvisionVersion,
    edition: CodeEdition,
    today: date | None = None,
) -> str:
    """``InForce`` or ``NotInForce``, computed — never assumed.

    Telling the world a 2006 text is current is the worst error this product
    can make, so the open-ended case is decided by :func:`effective_window`
    rather than by the version's own null end date.  A version that never
    governed a day is not in force whatever the calendar says.
    """
    if version.never_in_force:
        return "NotInForce"
    start, end = effective_window(version, edition)
    day = today or date.today()
    live = start <= day and (end is None or day < end)
    return "InForce" if live else "NotInForce"


def temporal_coverage(start: date, end: date | None) -> str:
    """The window as an ISO 8601 interval, or "" when it covers no day.

    Two conversions happen here, and both are off-by-one traps:

    * The stored window is half-open — ``effective <= d < ineffective`` — but
      an ISO interval includes **both** endpoints.  So the printed end is the
      day *before* ``end``.  Writing ``end`` itself claims the text applied on
      the first day it did not.
    * An open window is ``2012-01-01/..``.  Never today's date: the edition
      may have been superseded without this provision changing, and an end of
      "today" claims a currency nobody checked.
    """
    if end is None:
        return f"{start.isoformat()}/.."
    last_day = end - timedelta(days=1)
    if last_day < start:
        # Zero-duration or inverted window (``never_in_force``): the version is
        # a real link in the amendment chain but governed no day, and an
        # interval is the wrong shape for that.  Say nothing instead.
        return ""
    return f"{start.isoformat()}/{last_day.isoformat()}"


def _base_regulation(edition: CodeEdition) -> Regulation | None:
    """The instrument that enacted this edition, if it is loaded."""
    return Regulation.objects.filter(
        edition=edition, role=Regulation.Role.BASE
    ).first()


def _amending_regulations(version: CodeEditionProvisionVersion) -> list[Regulation]:
    """The instruments that produced this version, in apply order.

    Empty for a base v0, which is correct: nothing amended it.  It is also
    empty when CCM shipped no contributing clause (the base-enactment gap), and
    the caller must treat both the same way — omit the property.  Falling back
    to the edition's base regulation would print a citation nobody verified.
    """
    seen: set[str] = set()
    out: list[Regulation] = []
    for row in version.codeeditionprovisionversionclause_set.select_related(
        "clause__regulation"
    ):
        reg = row.clause.regulation
        if reg.role == Regulation.Role.AMENDMENT and reg.reg_id not in seen:
            seen.add(reg.reg_id)
            out.append(reg)
    return out


def _regulation_node(reg: Regulation, origin: str) -> dict[str, Any]:
    """One ``Legislation`` node for a regulation.

    Used both nested (inside a provision's block) and as the base of the
    regulation page's own block.  One builder, because the two blocks link to
    each other and must name a regulation the same way.
    """
    node: dict[str, Any] = {
        "@type": "Legislation",
        "name": reg.reg_id,
        "legislationIdentifier": reg.reg_id,
        "url": f"{origin}{reverse('core:regulation_detail', args=[reg.pk])}",
    }
    if reg.source_url:
        # The instrument as published elsewhere — e-Laws, a gazette scan.
        # ``sameAs`` says "the same thing, over there", which is what a
        # source link is; it does not claim we host that page.
        node["sameAs"] = reg.source_url
    return node


def _edition_node(edition: CodeEdition, origin: str) -> dict[str, Any]:
    """The ``isPartOf`` node — the edition a provision or regulation belongs to."""
    return {
        "@type": "Legislation",
        "name": f"{get_code_display_name(edition.code.code)} {edition.edition_id}".strip(),
        "url": f"{origin}{reverse('core:edition_chain', args=[edition.pk])}",
    }


def _serialize(block: dict[str, Any]) -> SafeString:
    """Drop the unsourced keys, serialize, and escape for a ``<script>``.

    One serializer for every block on the site.  Two would eventually differ
    on the escaping, and the escaping is the part that fails silently.

    An empty value means "not sourced", and it is dropped rather than emitted:
    a blank name is worse than no name, and a missing property costs less than
    a wrong one once a machine repeats it.
    """
    kept = {key: value for key, value in block.items() if value not in ("", None, [])}
    return mark_safe(json.dumps(kept, ensure_ascii=False).translate(_SCRIPT_ESCAPES))


def _citation(provision: CodeEditionProvision, base_reg: Regulation | None) -> str:
    """The provision as a person would cite it.

    ``legislationIdentifier`` is meant to be the official citation, and the
    bare provision number is not one: "3.2.5.7." exists in OBC 2006, in OBC
    2012, and in more than one division.  Qualifying it by level, division and
    instrument makes the identifier stand on its own, which is the point of an
    identifier.  Each qualifier is dropped when it is not known.
    """
    parts = []
    if provision.level:
        parts.append(provision.level.capitalize())
    parts.append(provision.provision_id)
    if provision.division:
        parts.append(f"of Division {provision.division}")
    if base_reg:
        parts.append(f"of {base_reg.reg_id}")
    return " ".join(parts)


def provision_jsonld(
    provision: CodeEditionProvision,
    version: CodeEditionProvisionVersion,
    *,
    origin: str,
    today: date | None = None,
) -> SafeString:
    """The ``schema.org/Legislation`` block for one provision-version page.

    Returns the serialized JSON, ready to print inside a
    ``<script type="application/ld+json">``, or an empty string when the
    provision has no canonical URL to name.

    Two relations, not one.  A provision version *is* a consolidation, and the
    generic ``isBasedOn`` cannot tell apart the two instruments behind it:

    * ``legislationConsolidates`` — the base regulation the edition assembles.
      An edition-level fact, so it survives the base-enactment gap and is
      present even on a v0 with no contributing clause.
    * ``legislationChangedBy`` — the amending regulations that produced *this*
      version.  Absent on a v0, because nothing changed it.

    ``url`` is the CANONICAL url, not this page.  Every version page of one
    provision must name the same subject, or the chain describes itself as
    several different things and the canonical link is contradicted by the
    block beneath it.
    """
    edition = provision.edition
    canonical_version = canonical_version_number(provision)
    if canonical_version is None:
        return mark_safe("")

    base_reg = _base_regulation(edition)
    start, end = effective_window(version, edition)
    heading = (version.title or "").strip()
    canonical_path = provision_permalink_url(
        edition.code_name, provision.division, provision.provision_id, canonical_version
    )

    block: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        # Omitted rather than emitted empty when the provision has no heading:
        # a blank name is worse than none, and legislationIdentifier already
        # carries the identity.
        "name": heading,
        "legislationIdentifier": _citation(provision, base_reg),
        "legislationJurisdiction": JURISDICTION_URIS.get(edition.code.code, ""),
        # The date the instrument was ADOPTED, which belongs to the regulation,
        # not to the version.  Distinct from legislationDateVersion below —
        # collapsing the two dates back-dates every amendment to the edition.
        "legislationDate": (
            (base_reg.filed_date or base_reg.effective_date).isoformat()
            if base_reg
            else ""
        ),
        "legislationDateVersion": version.effective_date.isoformat(),
        "legislationLegalForce": legal_force(version, edition, today),
        "temporalCoverage": temporal_coverage(start, end),
        "inLanguage": "en",
        "isPartOf": _edition_node(edition, origin),
        "legislationConsolidates": (
            _regulation_node(base_reg, origin) if base_reg else None
        ),
        "legislationChangedBy": [
            _regulation_node(reg, origin) for reg in _amending_regulations(version)
        ],
        "url": f"{origin}{canonical_path}",
    }
    return _serialize(block)


def regulation_jsonld(regulation: Regulation, *, origin: str) -> SafeString:
    """The ``schema.org/Legislation`` block for one regulation detail page.

    A regulation *is* a piece of legislation, so the type describes it more
    exactly than it describes a provision.  It carries less, though: the
    provision pages are where the traffic and the in-force window are, and
    this block exists mainly so that the object a provision block names in
    ``legislationConsolidates`` has a description of its own when a crawler
    follows the link.

    Two properties are deliberately absent.  ``temporalCoverage`` and
    ``legislationLegalForce`` belong to a provision version, not to an
    instrument: an amendment is not superseded the way a text is — the change
    it made stays made.  To state a currency here invents a fact the data does
    not hold.
    """
    edition = regulation.edition
    adopted = regulation.filed_date or regulation.effective_date
    block: dict[str, Any] = {
        "@context": "https://schema.org",
        **_regulation_node(regulation, origin),
        "legislationJurisdiction": JURISDICTION_URIS.get(edition.code.code, ""),
        # The kind of instrument, which is what schema.org means by the term —
        # act, regulation, directive.  NOT ``Regulation.role``: base and
        # amendment are our word for the part a row plays in an edition, and
        # both rows are regulations.
        "legislationType": "Regulation",
        "legislationDate": adopted.isoformat() if adopted else "",
        "inLanguage": "en",
        "isPartOf": _edition_node(edition, origin),
        # The mirror of the provision block's ``legislationChangedBy``: there
        # the version names what changed it, here the instrument names what it
        # changes.  Absent on a base regulation, which amends nothing.
        "legislationChanges": (
            _regulation_node(regulation.amends, origin) if regulation.amends else None
        ),
    }
    return _serialize(block)
