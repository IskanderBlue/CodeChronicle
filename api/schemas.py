"""What the API returns, stated once and in full.

Until now ``/api/search`` declared its results as ``list[dict]``.  Two things
were wrong with that.  A caller reading ``/api/docs`` learnt nothing about a
result beyond the word "object".  And the dicts it meant to send are the ones
``api.formatters`` builds for the **templates**, which carry live Django model
instances under keys like ``version`` and ``provision`` — the JSON encoder
raises ``TypeError`` on the first one, so the endpoint could not answer a
search that matched anything.  Every test mocked the formatter to ``[]``, so
nothing caught it.

The schemas below are a deliberate projection, not a dump.  Adding a field is
a decision made here, in one place, and ``/api/docs`` states the result of that
decision to the caller without anybody writing it down twice.

**A card on the page is not a result here.**  The page groups matches into
cards — a parent with its matching children, or the two sides of an edition
transition — because that is how a person reads them.  A card has no single
identity: a group card carries a parent's number over its top child's text.
:func:`flatten` unpicks those into one entry per matched provision version,
which is the thing a caller can cite, count and loop over.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ninja import Schema

from core.code_names import edition_display_name
from core.permalinks import provision_permalink_url
from core.seo import last_governed_day


class TableOut(Schema):
    """A table belonging to the provision version."""

    id: str
    caption: str
    #: The table as e-Laws marks it up.  Empty when the edition ships the table
    #: only as a page scan.
    html: str
    #: Notes below the table.  Standalone content that ``html`` does not carry,
    #: so a caller that drops this loses text the regulation contains.
    notes: str


class VersionOut(Schema):
    """Which text this is, and the days it governs."""

    number: int
    effective_date: date | None
    #: The day the version stops governing — **exclusive**.  The stored window
    #: is half-open, so this date is the first day the *next* text applies.
    ineffective_date: date | None
    #: The last day this text actually governs, for a citation that says "to".
    #: ``core.seo.last_governed_day`` computes it for the whole product, so an
    #: API caller and a printed exhibit cannot disagree by a day.  ``null``
    #: means the text is still in force.
    last_governed_day: date | None
    #: ``true`` for the text as the edition was made; ``false`` once an
    #: amending regulation has changed it.
    is_base: bool
    #: The amending regulation that produced this text, as it is cited.
    #: ``null`` on a base version.
    amended_by: str | None


class ResultOut(Schema):
    """One match: which provision, which version, and why it ranked.

    **The map, not the territory.**  A search says where to look; it does not
    hand over the text.  That mirrors how the page is read — a reader scans
    numbers, titles and dates, and opens the two or three that look right —
    and it is what makes the text countable, because a text then leaves this
    product one provision at a time through ``/api/provision`` and every one
    is recorded.  Bundled a hundred to a call, nothing could say which
    provisions an account had taken.

    The fields here are exactly the arguments ``/api/provision`` takes, so a
    caller loops over these rows and fetches without composing anything.
    """

    id: str
    title: str
    #: "A", "B" or "C"; empty for an edition published without divisions.
    division: str
    #: The edition key, e.g. "OBC_2006" — what ``/api/codes`` lists.
    edition: str
    edition_name: str
    #: The provision that contains this one. Empty at the top of the tree.
    parent_id: str
    #: Path to this exact version on the website. It names the version rather
    #: than the provision, so it keeps pointing at the text that matched.
    url: str
    score: float
    #: How it matched: "exact", "synonym", "fuzzy" or "reference".
    match_type: str | None
    #: Query words that matched, as the caller typed them.
    matched_terms: list[str]
    #: Words the query parser added — a synonym, a plural. Scored lower.
    matched_terms_indirect: list[str]
    version: VersionOut


class SearchMetaOut(Schema):
    """What the search actually ran, which is not always what was asked."""

    query: str
    #: The date the search ran at. The ``date`` field of the request when it
    #: was sent; otherwise the date the parser read out of the query text.
    date: str | None
    province: str
    #: The keywords the parser resolved the query to.
    keywords: list[str]
    #: The editions searched, by the same keys ``/api/codes`` lists.
    editions_searched: list[str]
    result_count: int


def clause_citation(clause: Any) -> str | None:
    """How the amending regulation is cited, from the clause that applied it."""
    regulation = getattr(clause, "regulation", None)
    if regulation is None:
        return None
    return getattr(regulation, "citation", None) or getattr(regulation, "reg_id", None)


def _version_out(card: dict[str, Any]) -> VersionOut:
    version = card["version"]
    return VersionOut(
        number=version.version,
        effective_date=version.effective_date,
        ineffective_date=version.ineffective_date,
        last_governed_day=last_governed_day(version.ineffective_date),
        is_base=version.version == 0,
        amended_by=clause_citation(card.get("most_recent_clause") or card.get("clause")),
    )


def result_out(card: dict[str, Any]) -> ResultOut:
    """Project one formatted result onto the API's shape.

    Reads the formatted card rather than the raw search hit, so the API and the
    page agree about what matched and about which text was in force.  It takes
    only named keys: a field reaches a caller because somebody put it here.
    """
    edition = str(card.get("code_edition") or card.get("code") or "")
    version = card["version"]
    division = str(card.get("division") or "")
    provision_id = str(card.get("id") or "")
    url = (
        provision_permalink_url(edition, division, provision_id, version.version)
        if edition and provision_id
        else ""
    )
    return ResultOut(
        id=provision_id,
        title=str(card.get("title") or ""),
        division=division,
        edition=edition,
        edition_name=edition_display_name(edition) if edition else "",
        parent_id=str(card.get("parent_id") or ""),
        url=url,
        score=float(card.get("score") or 0),
        match_type=card.get("match_type"),
        matched_terms=list(card.get("matched_terms") or []),
        matched_terms_indirect=list(card.get("matched_terms_indirect") or []),
        version=_version_out(card),
    )


def flatten(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per matched provision version, in score order.

    The page's two grouping shapes come apart here:

    - **A parent with matching children.** The card itself is skipped, because
      its identity is mixed — it prints the parent's number above the top
      child's text, which reads correctly as a heading and would be a lie as a
      record. Its parts are emitted instead: the parent's own match when the
      parent was itself a hit, and every matched child. A context child that
      was not a hit carries no result and is not one.
    - **A transition pair.** Both sides are emitted, because both are real
      texts that governed on real days, and which one the caller wants is not
      ours to decide.

    Anything else is already one provision and passes through.
    """
    flat: list[dict[str, Any]] = []
    for card in cards:
        if card.get("result_type") == "transition_compare":
            flat.extend(card.get("versions") or [])
            continue
        if card.get("group_type") == "parent_children":
            parent_self = card.get("parent_result")
            if parent_self is not None:
                flat.append(parent_self)
            for child in card.get("children") or []:
                if child.get("result") is not None:
                    flat.append(child["result"])
            continue
        flat.append(card)
    flat.sort(key=lambda card: card.get("score") or 0, reverse=True)
    return flat


class ProvisionOut(Schema):
    """One provision version, with its text.

    What ``/api/provision`` answers with, and the only place the text leaves
    this product through the API.  It carries the same identity fields a
    search result does, so a caller can hold the two side by side, plus the
    body and the tables.
    """

    id: str
    title: str
    division: str
    edition: str
    edition_name: str
    parent_id: str
    url: str
    #: The provision text, as e-Laws marks it up.  Empty when the edition
    #: ships this provision only as a page scan, and empty on a part, section
    #: or division, which are headings and carry no text of their own.
    html: str
    #: ``true`` when this provision is a container — a part, section,
    #: subsection or division.  An empty ``html`` on one of these is correct
    #: and is not missing data.
    is_container: bool
    tables: list[TableOut]
    version: VersionOut


class ProvisionMetaOut(Schema):
    """Which version was served, and why that one."""

    #: The date asked for, when the request named one instead of a version.
    on: str | None
    #: How the version was chosen: "in_force_on" (the date) or "requested"
    #: (an explicit version number).
    resolved_by: str
    #: How many versions of this provision exist, so a caller knows whether
    #: there is history to walk.
    version_count: int
