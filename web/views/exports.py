"""Taking something out of CodeChronicle and putting it in your own work.

Four exports ship together — a citation string, a provision as a printable
page, a search result set as CSV, and a comparison as a printable page — and
each records an :class:`EngagementEvent` naming its kind.  Building all four
is the point: we do not know which one a code consultant reaches for, and
asking produces an opinion rather than a measurement.  After sixty days the
counts decide, and an export nobody used is removed rather than defended
(``tasks/b-provision-exports.md``).

Two rules hold across every export in this module:

* **The gate is the gate.**  Every entry point calls
  :func:`accounts.access.edition_allowed` before it renders anything.  A free
  reader exports what a free reader can read, and there is no second
  definition of a tier here.
* **The retrieval date is stated.**  A historical text with no retrieval stamp
  becomes an undated claim the moment it leaves the site.
"""

from __future__ import annotations

import csv
from datetime import date
from typing import Any

from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.access import edition_allowed
from core.code_names import edition_display_name
from core.models import EngagementEvent
from corpus.citations import LEGAL, REFERENCE, REPORT, build_citations
from corpus.lineage.compare import parse_version_ref, resolve_version_ref
from corpus.permalinks import provision_permalink_url, provision_print_url
from corpus.seo import site_origin
from data.exports import EXPORT_KIND_NAMES
from search.prefs import resolve_match_threshold
from search.service import run_search
from telemetry.events import record_event
from web.views.regulation import locked_edition_response, provenance_result

#: The citation formats.  ``reference`` is the structured provenance block the
#: band's copy button has always produced; it predates this card and is folded
#: into the same menu rather than left beside it, so one control answers "how
#: do I quote this" instead of two.  It is measured like the other two and can
#: lose.
CITATION_FORMATS = frozenset({LEGAL, REPORT, REFERENCE})


def _version_from_request(request: HttpRequest) -> Any:
    """Resolve ``?v=OBC_2006/B/3.2.5.7./v0`` into a version, or ``None``.

    One reference parameter rather than four, because it is the same string
    ``/compare/`` takes and the same shape a permalink path has — a reader who
    copies a URL has already produced it.
    """
    ref = parse_version_ref(request.GET.get("v") or request.POST.get("v"))
    if ref is None:
        return None
    return resolve_version_ref(ref)


def citation_panel(request: HttpRequest) -> HttpResponse:
    """The citation menu's contents, fetched when a reader opens it.

    Lazy on purpose.  A results page carries up to a hundred cards and almost
    nobody cites from more than one, so the strings are built for the card
    that was asked about rather than for every card that was drawn.

    Nothing is recorded here: opening a menu is not an export.  The copy is.
    """
    version = _version_from_request(request)
    if version is None:
        return HttpResponseBadRequest("Unknown provision version.")

    provision = version.provision
    edition = provision.edition
    if not edition_allowed(request.user, edition.code_name):
        return locked_edition_response(request, edition, surface="citation")

    # The amendment chain Reference prints.  It comes from the resolver the
    # reading surfaces already use, so the menu cannot state a chain the page
    # behind it does not.
    provenance = provenance_result(
        provision,
        version,
        edition.code_name,
        provision.division,
        provision.provision_id,
        user=request.user,
    )
    citations = build_citations(
        provision,
        version,
        origin=site_origin(request),
        retrieved=date.today(),
        provenance_lines=provenance["provenance_lines"],
    )
    return render(
        request,
        "partials/_citation_panel.html",
        {
            "citations": citations,
            "version_ref": request.GET.get("v", ""),
            # The exhibit lives one click from the citation, because both
            # answer "take this into my own work" and a reader looking for one
            # is the reader who might want the other.  It is not a citation
            # format, so it sits below them rather than among them.
            "print_url": provision_print_url(
                edition.code_name,
                provision.division,
                provision.provision_id,
                version.version,
            ),
            "print_needs_sign_in": not request.user.is_authenticated,
        },
    )


#: The CSV's columns, in order.  Deliberately short: a CSV with body text in
#: it is a spreadsheet nobody can read, and the body is one click away in the
#: URL column.
CSV_COLUMNS = [
    "provision_id",
    "division",
    "title",
    "edition",
    "effective_date",
    "ineffective_date",
    "score",
    "locked",
    "url",
]


def _csv_rows(result: dict[str, Any], origin: str) -> list[list[Any]]:
    """The result set as rows, in the order the reader saw it.

    Two kinds of row, and the ``locked`` column is what tells them apart.  An
    accessible row carries its dates and its score.  A locked row carries
    identity only — id, division, title, edition — because identity is all the
    screen ever showed for it, and inventing a score for a result we did not
    serve would be worse than a short row.

    The locked rows are the preview list, not every locked match: on screen the
    remainder was a number, never rows, and a CSV that turned that number into
    rows would contain something the reader was never shown.
    """
    rows: list[list[Any]] = []
    for card in result.get("results") or []:
        version = card.get("version")
        rows.append([
            card.get("id", ""),
            card.get("division", ""),
            card.get("title", ""),
            edition_display_name(card.get("code_edition", "")),
            getattr(version, "effective_date", "") or "",
            getattr(version, "ineffective_date", "") or "",
            card.get("score", ""),
            "false",
            origin + provision_permalink_url(
                card.get("code_edition", ""),
                card.get("division", ""),
                card.get("id", ""),
                getattr(version, "version", 0),
            ) if version is not None else "",
        ])
    for locked in result.get("locked_preview") or []:
        rows.append([
            locked.get("id", ""),
            locked.get("division", ""),
            locked.get("title", ""),
            edition_display_name(locked.get("code_edition", "")),
            "",
            "",
            "",
            "true",
            "",
        ])
    return rows


@require_POST
def results_csv(request: HttpRequest) -> HttpResponse:
    """The result set the reader is looking at, as a spreadsheet.

    The search is **re-run** rather than read back from anywhere, with the same
    query, the same date and province overrides and the same relevance floor
    the page posted.  That is what makes the export match the screen: the tier
    split, the floor and the render cap are all applied by the one pipeline, so
    there is no second definition of "what this reader can see" to drift.  An
    export that quietly contains more than the screen showed is worse than no
    export.

    Signed-in readers only.  The citation string is open to everybody because
    it carries our URL into somebody else's document; a result set is work
    product.
    """
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Sign in to export a result set.")

    query = request.POST.get("query", "")
    result = run_search(
        query,
        user=request.user,
        date_override=request.POST.get("date") or None,
        province_override=request.POST.get("province") or None,
        match_threshold=resolve_match_threshold(request),
    )
    if not result.get("success"):
        return HttpResponseBadRequest(result.get("error") or "The search failed.")

    record_event(
        request,
        event_type=EngagementEvent.EventType.EXPORT,
        search_id=result.get("search_history_id"),
        context={
            "kind": "results_csv",
            "rows": len(result.get("results") or []),
            "locked_rows": len(result.get("locked_preview") or []),
        },
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="codechronicle-results-{date.today().isoformat()}.csv"'
    )
    # utf-8-sig: Excel reads a plain UTF-8 CSV as Latin-1 and turns every
    # em dash in a provision title into mojibake.  The BOM is the only thing
    # that tells it otherwise, and a spreadsheet is where this file is opened.
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow(CSV_COLUMNS)
    writer.writerows(_csv_rows(result, site_origin(request)))
    return response


@require_POST
def record_export(request: HttpRequest) -> HttpResponse:
    """Record that a reader took an export, and return nothing to draw.

    The client has already copied to the clipboard or opened the print dialog
    by the time this runs; the response is empty because there is nothing to
    swap.  A rejected kind is dropped rather than recorded under a name the
    insights table does not know — a count that quietly includes junk is worse
    than a missing one.
    """
    kind = request.POST.get("kind", "")
    if kind not in EXPORT_KIND_NAMES:
        return HttpResponseBadRequest("Unknown export kind.")

    context: dict[str, Any] = {"kind": kind}
    fmt = request.POST.get("format", "")
    if kind == "citation":
        if fmt not in CITATION_FORMATS:
            return HttpResponseBadRequest("Unknown citation format.")
        context["format"] = fmt

    version = _version_from_request(request)
    object_id = None
    if version is not None:
        provision = version.provision
        edition = provision.edition
        # The gate again, on the write path.  A reader who cannot open an
        # edition cannot record an export of it either, or the counts would
        # measure attempts we refused as value delivered.
        if not edition_allowed(request.user, edition.code_name):
            return HttpResponseBadRequest("Not available on this plan.")
        object_id = version.pk
        context["provision_id"] = provision.provision_id
        context["division"] = provision.division
        context["code_edition"] = edition.code_name

    record_event(
        request,
        event_type=EngagementEvent.EventType.EXPORT,
        object_type="CodeEditionProvisionVersion" if object_id else "",
        object_id=object_id,
        search_id=request.POST.get("search_id"),
        context=context,
    )
    return HttpResponse(status=204)
