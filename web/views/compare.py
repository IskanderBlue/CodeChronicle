"""The comparison page: any two provision versions, side by side.

The comparison is a *page*, not a mode.  A reader arrives by a link and leaves
by browser back or by one of the two sides, each of which links to its own
permalink.  There is nothing to arm and nothing to cancel, which is why there
is no "stop comparing" control here.

The page drops the provenance rail that every other provision surface carries.
The rail states the provenance of *one* version, and here there are two; it
would have to pick a side or say everything twice.  The twin header is the
rail's content, re-cut for two.
"""

from datetime import date
from typing import Any

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from accounts.access import edition_allowed, edition_gate
from core.models import CodeEditionProvisionVersion, EngagementEvent
from corpus.cross_refs import annotate_versions
from corpus.lineage.compare import (
    REDLINE_FLOOR,
    pairing_basis,
    parse_version_ref,
    resolve_version_ref,
    version_ref,
    version_timeline,
)
from corpus.permalinks import provision_permalink_url
from corpus.printing.page_crops import build_crops
from corpus.printing.print_options import apply_tables_mode, resolve_tables_mode, toggle_query
from corpus.seo import TITLE_SUFFIX, exhibit_title, site_origin
from search.formatters.formatters import diff_html_content, diff_is_empty, diff_similarity
from telemetry.attribution import crown_years_for_provisions
from telemetry.events import record_event
from telemetry.reading_ledger import record_versions
from web.http_cache import corpus_conditional
from web.views.regulation import locked_edition_response


def comparison_side(version: CodeEditionProvisionVersion, label: str) -> dict[str, Any]:
    """One side of the comparison, with everything the twin header states."""
    provision = version.provision
    edition = provision.edition
    clause = version.last_contributing_clause
    # A v0 has no amending clause, and naming it "base" told the reader the
    # category and withheld the instrument — the one fact the row is for.
    # ``origin_regulation`` is the right source rather than the edition's base
    # reg: for a provision an amendment ADDED, the edition base never attested
    # it, so it is the introducing regulation that enacted this text.
    return {
        "label": label,
        "version": version,
        "provision": provision,
        "edition": edition,
        "edition_name": f"{edition.code.code} {edition.edition_id}".strip(),
        "regulation": (
            clause.regulation if clause is not None else provision.origin_regulation
        ),
        # Whether that regulation ENACTED this text or amended it. Both are
        # "the instrument behind this version", and a comparison that showed
        # them identically would flatten a distinction the product spends the
        # rest of its surface area making.
        "regulation_is_origin": clause is None,
        "url": provision_permalink_url(
            edition.code_name,
            provision.division,
            provision.provision_id,
            version.version,
        ),
        "ref": version_ref(version).path,
    }


def _missing(request: HttpRequest, message: str) -> HttpResponse:
    """A comparison that cannot be built, said plainly rather than 404ed.

    A reader reaches this by editing a URL or by following a link to a
    provision that has since been reloaded under different ids.  Naming what
    is wrong is more use than a 404, and the page offers the search box.
    """
    return render(
        request,
        "compare_missing.html",
        {
            "message": message,
            "meta_title": f"Comparison not found{TITLE_SUFFIX}",
            "meta_description": (
                "This comparison names a provision version that is not in the "
                "corpus."
            ),
        },
        status=404,
    )


@corpus_conditional
def compare_versions(request: HttpRequest, for_print: bool = False) -> HttpResponse:
    """Compare the two versions named by ``?a=`` and ``?b=``.

    Both references use the permalink path form, so a reader builds a
    comparison by copying two URLs.  The pair is ordered by effective date
    before rendering, not by which parameter it arrived in: a comparison reads
    earlier-to-later whichever way round the reader named it.

    ``for_print`` (the ``/compare/print/`` route) renders the same comparison
    as an exhibit.  One view, because the printed comparison has to state the
    same two windows, the same instruments and the same caveats as the page —
    and a second assembly is how that stops being true.
    """
    ref_a = parse_version_ref(request.GET.get("a"))
    ref_b = parse_version_ref(request.GET.get("b"))
    if ref_a is None or ref_b is None:
        return _missing(
            request,
            "A comparison needs two versions, each named the way a permalink "
            "names one — for example OBC_2006/B/3.2.5.7./v0.",
        )

    version_a = resolve_version_ref(ref_a)
    if version_a is None:
        return _missing(
            request,
            f"{ref_a.provision_id} v{ref_a.version} is not in {ref_a.code_edition}.",
        )
    version_b = resolve_version_ref(ref_b)
    if version_b is None:
        return _missing(
            request,
            f"{ref_b.provision_id} v{ref_b.version} is not in {ref_b.code_edition}.",
        )

    if version_a.pk == version_b.pk:
        return _missing(
            request, "A comparison needs two different versions.",
        )

    # Gate both sides.  Same-edition comparison inside the free tier passes;
    # a cross-edition pair with one side outside it does not.  This is the
    # tier rule applied twice, never a second definition of a tier.
    for version in (version_a, version_b):
        edition = version.provision.edition
        if not edition_allowed(request.user, edition.code_name):
            return locked_edition_response(request, edition, surface="compare")

    # A comparison reads earlier-to-later whichever way round the reader named
    # it.  A version that was never in force has no effective date; it sorts
    # first rather than raising, and the header says "never in force" for it.
    earlier, later = sorted(
        (version_a, version_b),
        key=lambda v: (v.effective_date or date.min, v.version),
    )

    cross_edition = earlier.provision.edition_id != later.provision.edition_id

    if for_print and not request.user.is_authenticated:
        # Same line as the printable provision: a citation is open to
        # everybody because it carries our URL out into the world; an exhibit
        # is work product.
        return redirect_to_login(request.get_full_path())

    # Engagement.  After the gate, so a refusal counts as a
    # LOCKED_CONTENT_VIEW and never also as value delivered — the two numbers
    # are the numerator and the denominator of the same question.  The object
    # is the later version, because that is the one the reader was almost
    # always looking at when they asked.  Non-fatal.
    #
    # A print is an *export*, not a comparison view: counting it as both would
    # inflate the comparison total with the readers who exported one, and the
    # export counts have to be readable against it.
    record_event(
        request,
        event_type=(
            EngagementEvent.EventType.EXPORT
            if for_print
            else EngagementEvent.EventType.VERSION_COMPARISON
        ),
        object_type="CodeEditionProvisionVersion",
        object_id=later.pk,
        search_id=request.GET.get("search_id"),
        context={
            **({"kind": "comparison_pdf"} if for_print else {}),
            "a": version_ref(earlier).path,
            "b": version_ref(later).path,
            "cross_edition": cross_edition,
        },
    )

    # The reading ledger: a comparison delivers both texts in full, so both go
    # in.  The print branch too — an exhibit is the same two texts on paper.
    record_versions(request, (earlier, later))

    # Turn each side's citations into permalinks, one query per side.  A
    # citation is a link on every other provision surface, and a reader who
    # follows one out of a comparison is doing exactly what a comparison
    # prompts.  Per side, because ``annotate_versions`` scopes the links to one
    # edition and a cross-edition pair has two — a citation in the 1997 text
    # must resolve inside OBC 1997, not inside the edition on the other side.
    for version in (earlier, later):
        annotate_versions([version], version.provision.edition.code_name)

    basis = pairing_basis(earlier, later)
    similarity = diff_similarity(earlier.html, later.html)
    forced = request.GET.get("redline") == "on"
    # Below the floor a redline is two panes of almost entirely marked text.
    # The reader may disagree with the threshold, so the fallback is a default
    # and not a verdict: `?redline=on` draws it anyway.
    redline = forced or similarity >= REDLINE_FLOOR

    old_diff, new_diff = (None, None)
    if redline:
        # Diff the linked bodies, so the citations survive into the redline.
        # The differ passes tags through untouched and compares words only, so
        # the anchors change neither what is marked nor where.
        old_diff, new_diff = diff_html_content(
            earlier.linked_html or earlier.html,
            later.linked_html or later.html,
        )

    side_a = comparison_side(earlier, "A")
    side_b = comparison_side(later, "B")
    # The mapping's own direction, which is edition order and not always the
    # order the two sides are drawn in.  The sentence on the page reads
    # "maps X to Y", so it names these rather than A and B.
    basis_source, basis_target = (
        (side_b, side_a) if basis.reversed_ else (side_a, side_b)
    )
    title = (
        f"{side_a['provision'].provision_id} — "
        f"{side_a['edition_name']} compared with {side_b['edition_name']}"
    )

    tables_separate = False
    tables_mode = resolve_tables_mode(request.GET.get("tables"))
    if for_print:
        # Crops for the panes.  A pane falls back to the shared provision
        # content when there is nothing to redline — an image-only version
        # cannot be word-diffed — and that partial reads `version.crops` on a
        # print surface.
        for version in (earlier, later):
            version.crops = build_crops(version.page_images)
        # Same rule as the printable provision: a scanned page already shows
        # its tables, so repeating them as figures prints each one twice.
        tables_separate = apply_tables_mode([earlier, later], tables_mode)

    return render(
        request,
        "compare_print.html" if for_print else "compare.html",
        {
            "print_mode": for_print,
            "tables_separate": tables_separate,
            # Whether the page decided, or the reader did.  The control
            # explains itself only in the first case — see the print controls.
            "tables_by_default": tables_mode is None,
            "tables_toggle_query": toggle_query(request.GET, tables_separate),
            "retrieved": date.today(),
            "site_origin": site_origin(request),
            "comparison_path": (
                f"{reverse('web:compare')}"
                f"?a={side_a['ref']}&b={side_b['ref']}"
            ),
            "side_a": side_a,
            "side_b": side_b,
            # Both sides: a cross-edition pair is two provisions first
            # enacted by two different instruments, in two different years.
            "crown_years": crown_years_for_provisions(
                [earlier.provision, later.provision]
            ),
            # The same two dicts as a list, because the twin header loops over
            # them and a Django `for` cannot take a tuple literal.
            "sides": [side_a, side_b],
            "old_diff": old_diff,
            "new_diff": new_diff,
            "redline": redline,
            # True only when the floor is what suppressed the redline, so the
            # page explains the fallback rather than the reader guessing.
            "redline_suppressed": not redline,
            "redline_forced": forced,
            # Stated above the panes.  A redline marks what changed, so an
            # unmarked pair and an unfinished read look the same until the
            # reader has been through both columns to the end.
            "text_unchanged": diff_is_empty(earlier.html, later.html),
            "similarity_pct": round(similarity * 100),
            "basis": basis,
            "basis_source": basis_source,
            "basis_target": basis_target,
            "timeline": version_timeline(earlier, later, edition_gate(request.user)),
            "cross_edition": cross_edition,
            "force_redline_url": (
                f"?a={side_a['ref']}&b={side_b['ref']}&redline=on"
            ),
            # A printed comparison is a file somebody keeps, so its title is
            # written as that file's name; on screen the reading title stands.
            "meta_title": (
                exhibit_title(
                    f"Comparison {side_a['edition_name']} "
                    f"{side_a['provision'].provision_id} v{side_a['version'].version} "
                    f"vs {side_b['edition_name']} "
                    f"{side_b['provision'].provision_id} v{side_b['version'].version}",
                    date.today(),
                )
                if for_print
                else f"{title}{TITLE_SUFFIX}"
            ),
            "social_title": title,
            "meta_description": (
                f"{side_a['provision'].provision_id} as it read in "
                f"{side_a['edition_name']}, beside "
                f"{side_b['provision'].provision_id} in "
                f"{side_b['edition_name']}, with the amending regulations named."
            ),
        },
    )
