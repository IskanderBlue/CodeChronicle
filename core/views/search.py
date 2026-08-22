"""Search-related views."""

import json
from datetime import date
from typing import Any
from urllib.parse import urlencode

from coloured_logger import Logger
from django.db.models import F, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from api.formatters import code_order_key, highlight_terms
from api.schemas import flatten
from api.search.orchestration import identity_preview
from config.part_applicability import (
    AREA_UNITS,
    DEFAULT_AREA_UNIT,
    MAX_STOREYS,
    OCCUPANCIES,
    OCCUPANCY_SHORT,
    SQFT_PER_M2,
    Building,
    coerce_building,
    size_relevance_intervals,
    size_thresholds,
)
from config.search_limits import (
    CLOSE_MATCH_THRESHOLD,
    SCORE_BUCKET_WIDTH,
    SEARCH_RESULT_CAP,
)
from core.access import edition_allowed, edition_gate
from core.attribution import (
    crown_years_for_editions,
    crown_years_for_provisions,
    merge_years,
)
from core.code_names import edition_display_name, get_code_display_name
from core.events import record_event
from core.ip_utils import extract_client_ip
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
)
from core.provision_lineage import (
    LineageDirection,
    annotate_lineage_locks,
    annotate_lineage_titles,
    resolve_lineage,
)
from core.reading_ledger import record_reads, record_versions
from core.search_prefs import resolve_match_threshold
from core.seo import TITLE_SUFFIX
from core.subtrees import contents_view, walk_subtree
from services.search_service import run_search

logger = Logger(__name__)


def _query_value(request: HttpRequest, key: str) -> str:
    value = request.GET.get(key)
    return value if isinstance(value, str) else ""


#: What the building control posts, and what the address carries.  The
#: reader's own number and unit, not the derived metric value: ``area_m2`` is
#: computed from these two and would be a conversion of the reader's figure
#: rather than the figure, which is not what an address a person reads should
#: name.  Written once so the form, the address and the seed agree.
BUILDING_FIELDS = ("occupancy", "storeys", "area", "area_unit")


def _size_relevance() -> list[dict[str, Any]]:
    """When a measurement can decide, shaped for the control's json_script.

    The control watches the AS-OF picker and asks for a size only where a size
    changes the answer on that day.  The edition windows come from the corpus
    rather than from a constant, so an edition that is not loaded contributes
    no interval and the control never offers a field about an edition the
    reader cannot reach.
    """
    windows = {
        edition_id: (start, end)
        for edition_id, start, end in CodeEdition.objects.values_list(
            "edition_id", "effective_date", "ineffective_date"
        )
    }
    return [
        {
            "from": window.start.isoformat() if window.start else None,
            "until": window.end.isoformat() if window.end else None,
            "sized": sorted(window.sized),
        }
        for window in size_relevance_intervals(windows)
    ]


def _building_control_context() -> dict[str, Any]:
    """Everything the BUILDING control needs, for the views that render it.

    One builder rather than the dict written twice: the search page renders
    the form, and anything else that grows a copy of it should get the same
    keys without keeping them in step by hand.

    Deliberately NOT part of the results-partial context.  The control lives
    in the search form, which the htmx results swap never re-renders, so a
    copy there would be four dead keys and a ``CodeEdition`` query on every
    search.
    """
    return {
        "occupancy_choices": OCCUPANCIES,
        "area_units": AREA_UNITS,
        "max_storeys": MAX_STOREYS,
        "size_thresholds": size_thresholds(),
        # Everything the Alpine component cannot read off the form itself.
        # One blob, through json_script, the way the relevance control's
        # ``cc-datum-data`` works — an attribute cannot carry JSON without
        # closing on its own quotes, and a Python ``None`` inlined into
        # JavaScript is a ReferenceError.
        "building_data": {
            "windows": _size_relevance(),
            "labels": OCCUPANCY_SHORT,
            "sqftPerM2": SQFT_PER_M2,
        },
    }


def _building_from(source: Any) -> Building:
    """The building the reader told us about, validated.

    ``source`` is ``request.POST`` or ``request.GET`` — the control posts these
    names, and a shared or bookmarked address carries the same ones.
    """
    return coerce_building(
        source.get("occupancy"),
        source.get("storeys"),
        source.get("area"),
        source.get("area_unit") or DEFAULT_AREA_UNIT,
    )


def _announce_parsed_occupancy(
    response: HttpResponse, *, reader_chose: bool, building: Building
) -> HttpResponse:
    """Tell the form which occupancy the parser read out of the query.

    The BUILDING modal asks for a size only once an occupancy is named, and a
    reader who typed "house" has named one — in words the parser understood,
    not in the dropdown.  Without this the size fields never appear for them,
    so the boost only ever moves an assembly, care or high-hazard query, where
    the occupancy alone decides.

    **It fires only when the reader chose nothing.**  A stated occupancy is
    the reader's own answer and is never overwritten; the whole contract of
    the "Read it from my query" option runs reader-over-model, and this is the
    model filling a blank, in the one direction it is allowed to.

    ``reader_chose`` is the *coerced* answer, not the raw post, so
    ``coerce_building`` stays the single authority on what counts as a stated
    occupancy — a value it rejects must not silently suppress the reading.

    Sent as ``HX-Trigger`` rather than rendered into the results partial,
    because the field it updates lives in the search form — outside the
    swapped fragment, and outside its Alpine scope.
    """
    if reader_chose:
        return response
    occupancy = building.get("occupancy")
    if occupancy:
        response["HX-Trigger"] = json.dumps(
            {"cc-occupancy-read": {"occupancy": occupancy}}
        )
    return response


def _push_search_url(
    response: HttpResponse,
    query: str,
    day: str | None,
    *,
    replace: bool,
    building: Building | None = None,
) -> HttpResponse:
    """Put the search that just ran into the address bar.

    The results arrive by ``hx-post``, so without this the address stays
    ``/search/`` and a reload throws the search away.  The header rewrites it
    to the ``?q=``/``?d=`` form the page already understands, and that page
    auto-runs a seeded query — so a reload, a bookmark and a link a reader
    sends somebody all reproduce the search.

    It happens **here** rather than in the browser because the address must
    name the search that ran.  The AS-OF picker overrides whatever date the
    parser reads out of the query text, so ``day`` is the picker's value; a
    script copying the form could name a date the search did not use.

    **A new search earns a history entry; re-measuring one does not.**  The
    relevance-floor control re-posts through this same view by itself, without
    the reader touching the form, so an entry per drag would make Back a list
    of knob positions rather than a list of questions.  The building is the
    other case: it lives in the search form, so changing it means pressing
    Search, and the address that results differs from the one before it —
    somewhere real for Back to return to.  ``replace`` tells the two apart,
    and the caller decides it from the post itself rather than by comparing
    addresses, which the server cannot see.

    ``day`` is omitted when empty.  A seeded page with no ``?d=`` searches at
    the corpus default, which is the date this search used.

    ``building`` rides along for the same reason ``day`` does: it changes the
    order of the answer, so an address without it reproduces the words and not
    the page.  It carries the reader's own facts in the reader's own words and
    the reader's own units — ``occupancy=residential&storeys=4&area=1500&
    area_unit=sqft``.  Never the group letter ``C`` and never the converted
    ``area_m2``: one is an internal token and the other is our arithmetic on
    their figure, and neither is what they typed.
    """
    params = {"q": query}
    if day:
        params["d"] = day
    # A plain dict for the loop: BUILDING_FIELDS reads keys by name, and a
    # TypedDict cannot be subscripted by a variable.
    stated: dict[str, object] = dict(building or {})
    for field in BUILDING_FIELDS:
        value = stated.get(field)
        if value is not None:
            params[field] = str(value)
    header = "HX-Replace-Url" if replace else "HX-Push-Url"
    response[header] = f"{reverse('core:search')}?{urlencode(params)}"
    return response



def _lineage_nav_direction(direction: LineageDirection) -> dict[str, Any]:
    """Shape one lineage direction for the viewer nav partial.

    Linked rows become in-viewer load buttons, so each entry carries the
    ``data-edition-result`` payload fields (id/title/code/
    code_display_name/division — query_date/query_code are re-stamped by
    the click handler); marker states pass through as ``state`` +
    ``edition_label``.
    """
    links = []
    for link in direction.links:
        target = link.provision
        links.append({
            "verb": link.verb,
            "same_id": link.same_id,
            "same_edition": link.same_edition,
            "locked": link.locked,
            "edition_label": f"{link.edition.code.code} {link.edition.edition_id}",
            "id": target.provision_id,
            "title": link.title or target.provision_id,
            "code": link.edition.code_name,
            "code_display_name": (
                f"{get_code_display_name(link.edition.code.code)} "
                f"{link.edition.edition_id}"
            ).strip(),
            "division": target.division,
        })
    return {
        "state": direction.state,
        "edition_label": (
            f"{direction.edition.code.code} {direction.edition.edition_id}"
            if direction.edition else ""
        ),
        "links": links,
        "outside_corpus": direction.outside_corpus,
        "outside_reference": direction.outside_reference,
    }


# One-click example queries shown in the empty search state. Curated, not
# data-driven: each must return a real result with its FIRST hit in a
# supported edition (OBC 2006 — 1997 isn't supported yet), and the set spans
# the search modes — natural-language keywords and a bare article reference
# (exercises extract_section_references).  Every chip carries a ``date`` — it
# sets the AS-OF picker on click (the picker always overrides the date the LLM
# reads from the text), and an undated chip would search today, which falls
# outside every loaded edition's window and returns nothing.
#
# The reference chip does double duty: C 1.10.2.4. at 2014-07-01 is one of only
# three provisions whose OBC 2006 and 2012 versions are in force at the same
# time (2014-01-01 .. 2016-01-01), so the reference path returns both and the
# result is a transition_compare card — the diff view one click from an empty
# page.  Article 3.1.8.1. used to hold this slot; it was picked arbitrarily as
# "any article reference" (tasks/complete/intro-explanation-page.md) and had no
# reason to stay once a reference could demonstrate two things at once.
#
# Caveat: the free tier is scoped to OBC 2006 (core.access), so it sees only the
# 2006 half and gets a plain single result — the compare card renders for Pro.
# Do NOT re-point the keyword chips at a transition; the pair ranks 14/15 for
# "maintenance inspection", below the 10-card cut, which is why the old claim
# that that chip produced a card was wrong.
EXAMPLE_QUERIES = [
    {"query": "fire separation between dwelling units, Ontario, 2010", "date": "2010-06-01"},
    {"query": "guards and handrails for a stairway", "date": "2010-06-01"},
    {
        "query": "when must a maintenance inspection be conducted, Ontario, 2014",
        "date": "2014-07-01",
    },
    {"query": "1.10.2.4.", "date": "2014-07-01"},
]


def search_page(request):
    """Main search page — the product surface, at ``/search/``.

    ``/`` is the public landing page (``core.views.landing``); it redirects a
    signed-in reader here, so this stays one click from the masthead.
    """
    initial_query = request.GET.get("q", "")
    # ``?d=`` seeds the AS-OF picker.  The picker is the date the search
    # actually uses (it overrides whatever the parser reads out of the query
    # text), so a link that carries only ``?q=`` runs a query saying "1999" at
    # the default AS-OF date and returns a later edition.  Validated here, and
    # ignored when malformed, so a hand-edited URL cannot put junk in the
    # field.
    # Kept as a ``date``, not the raw string: the template runs it through the
    # ``date`` filter alongside the corpus default, and that filter returns an
    # empty string for a str input — which would silently blank the field.
    initial_date: date | None = None
    raw_date = request.GET.get("d", "")
    if raw_date:
        try:
            initial_date = date.fromisoformat(raw_date)
        except ValueError:
            initial_date = None
    return render(
        request,
        "search.html",
        {
            # The tab label and the social card, from one pair of strings.
            # The tab wants the short form; a forwarded link wants a sentence
            # that says what the page does, so the two differ on purpose and
            # each is written once.
            "meta_title": f"Search{TITLE_SUFFIX}",
            "social_title": "Search the Ontario Building Code by date",
            "meta_description": (
                "Ask a question in plain language, pick a date, and read the "
                "provisions that were in force on that date."
            ),
            "initial_query": initial_query,
            "initial_date": initial_date,
            # Seeds the auto-run with the building the address names, so a
            # history click, a bookmark and a forwarded link reproduce the
            # *order* of the results and not only the words.  Validated by the
            # same function the post uses, so a hand-edited address cannot
            # seed a value the control could not draw.
            "initial_building": _building_from(request.GET),
            "example_queries": EXAMPLE_QUERIES,
            # The BUILDING control, which lives in the search form so a reader
            # meets it before the first search rather than hunting for it.
            **_building_control_context(),
        },
    )


def viewer_edition_nav(request: HttpRequest):
    """HTMX partial: provision lineage rows for the client-side viewer overlay.

    The old prev/next-edition buttons guessed a same-id equivalent in the
    adjacent edition; these rows come from the lineage resolver instead
    (mapping rows > dispositions > same-id fallback on covered transitions
    — ``core.provision_lineage``).  Linked rows keep the in-viewer load
    behaviour via the ``data-edition-result`` payload; rows whose target
    edition is outside the user's free-tier scope render as a locked
    upsell to pricing (teaser, not omission).
    """
    code = _query_value(request, "code")
    # Accept new-style ``provision_id`` and legacy ``node_id`` for the
    # rollout window; the underlying value is the same.
    node_id = (
        _query_value(request, "provision_id")
        or _query_value(request, "node_id")
    )
    query_date = _query_value(request, "query_date")
    query_code = _query_value(request, "query_code")
    division = _query_value(request, "division")

    matched = None
    if code and "_" in code and node_id:
        system_code, edition_id = code.split("_", 1)
        matched = (
            CodeEditionProvision.objects
            .filter(
                edition__code__code=system_code,
                edition__edition_id=edition_id,
                division=division or "",
                provision_id=node_id,
            )
            .first()
        )

    predecessors = None
    successors = None
    if matched is not None:
        lineage = resolve_lineage([matched])[matched.pk]
        annotate_lineage_locks([lineage], edition_gate(request.user))
        # Titles come from the annotator, which reads each link's *own*
        # version rather than the target's latest.  This view used to take
        # the latest title; a title can change between versions, so the two
        # disagree, and the link must name the page it opens.
        annotate_lineage_titles([lineage])
        predecessors = _lineage_nav_direction(lineage.predecessors)
        successors = _lineage_nav_direction(lineage.successors)

    return render(
        request,
        "partials/_viewer_edition_nav.html",
        {
            "predecessors": predecessors,
            "successors": successors,
            "query_date": query_date,
            "query_code": query_code,
        },
    )


def viewer_edition_dates(request: HttpRequest):
    """HTMX partial: edition date range and lingering validity for browse context."""
    code = _query_value(request, "code")
    query_date = _query_value(request, "query_date")

    edition_info: dict[str, Any] = {}
    if code and "_" in code:
        system_code, edition_id = code.split("_", 1)
        edition = (
            CodeEdition.objects.select_related("code")
            .filter(code__code=system_code, edition_id=edition_id)
            .first()
        )
        if edition:
            edition_info["effective_date"] = edition.effective_date.isoformat()
            edition_info["ineffective_date"] = (
                edition.ineffective_date.isoformat()
                if edition.ineffective_date else None
            )
            edition_info["code_name"] = code
            edition_info["code_display_name"] = (
                f"{get_code_display_name(edition.code.code)} {edition.edition_id}".strip()
            )

            # Lingering-validity / transitions: any edition of the same
            # code whose in-force window overlaps this edition's.  Per
            # the new provenance schema, transitions are version
            # overlaps — we surface the edition-level overlap here and
            # let the search view render per-provision transition prose
            # from CodeEditionProvisionVersion.transition_provision.
            transitions = []
            this_start = edition.effective_date
            this_end = edition.ineffective_date
            overlapping = (
                CodeEdition.objects.filter(code=edition.code)
                .exclude(pk=edition.pk)
                .filter(effective_date__lt=(this_end or date.max))
                .filter(
                    Q(ineffective_date__isnull=True)
                    | Q(ineffective_date__gt=this_start)
                )
                # Stable order so the rendered transitions list doesn't
                # reshuffle between identical requests (DB heap order otherwise).
                .order_by("effective_date", "edition_id")
            )
            for other in overlapping:
                other_start = max(this_start, other.effective_date)
                other_end_candidates = [d for d in (this_end, other.ineffective_date) if d]
                other_end = min(other_end_candidates) if other_end_candidates else None
                transitions.append({
                    "old_edition": (
                        code if this_start <= other.effective_date else other.code_name
                    ),
                    "new_edition": (
                        other.code_name if this_start <= other.effective_date else code
                    ),
                    "overlap_start": other_start.isoformat(),
                    "overlap_end": other_end.isoformat() if other_end else None,
                    "transition_type": "edition overlap",
                })
            edition_info["transitions"] = transitions

    return render(
        request,
        "partials/_viewer_edition_dates.html",
        {"edition": edition_info, "query_date": query_date},
    )


def _parse_query_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def in_force_versions(
    provisions, query_date: date,
) -> list[CodeEditionProvisionVersion]:
    """Return the in-force versions for each provision at ``query_date``.

    Filters out the contract's zero-width "as-filed but superseded same
    day" emissions (``ineffective_date == effective_date``) — those are
    legal in the JSON but never apply.
    """
    versions = (
        CodeEditionProvisionVersion.objects
        .filter(provision__in=provisions)
        .filter(effective_date__lte=query_date)
        .filter(
            Q(ineffective_date__isnull=True)
            | Q(ineffective_date__gt=query_date)
        )
        .exclude(ineffective_date=F("effective_date"))
        .select_related("transition_provision__provision")
        .prefetch_related("tables", "contributing_clauses__regulation")
        .order_by("provision_id", "version")
    )
    return list(versions)


def viewer_section_content(request: HttpRequest):
    """HTMX partial: provision content for the viewer overlay.

    Reads the provenance schema: emits the in-force
    ``CodeEditionProvisionVersion`` rows for the provision's parent
    subtree at ``query_date``.  URL parameters: ``code`` (e.g. "OBC"),
    ``edition_id`` (e.g. "1997"), ``division``, ``provision_id``,
    ``query_date`` (default: today).
    """
    code = _query_value(request, "code")
    edition_id = _query_value(request, "edition_id")
    division = _query_value(request, "division")
    provision_id = _query_value(request, "provision_id")
    query_date = _parse_query_date(_query_value(request, "query_date")) or date.today()
    match_terms = [t for t in _query_value(request, "keywords").split(",") if t.strip()]

    empty_ctx = {
        "sections": [],
        "active_node_id": provision_id,
        "active_provision_id": provision_id,
        "transition_active": False,
    }
    if not code or not edition_id or not provision_id:
        return render(request, "partials/_viewer_section_content.html", empty_ctx)

    # Free-tier gate: provision content from an edition outside the user's
    # scope renders as a locked teaser instead of the text.  The refusal is
    # recorded as a locked_content_view — the user asked for this provision by
    # name and was turned away, which is the conversion signal, not a non-event.
    # Guarded on HX-Request for the same reason the view capture below is: only
    # a genuine drill-in counts, not a crawler or a refreshed URL.
    if not edition_allowed(request.user, f"{code}_{edition_id}"):
        if request.headers.get("HX-Request"):
            record_event(
                request,
                event_type=EngagementEvent.EventType.LOCKED_CONTENT_VIEW,
                object_type="CodeEditionProvision",
                search_id=request.GET.get("search_id"),
                context={
                    "surface": "search_viewer",
                    "code_edition": f"{code}_{edition_id}",
                    "provision_id": provision_id,
                    "division": division,
                },
            )
        return render(
            request,
            "partials/_viewer_section_content.html",
            {
                **empty_ctx,
                "locked_edition_name": f"{get_code_display_name(code)} {edition_id}".strip(),
            },
        )

    matched = (
        CodeEditionProvision.objects
        .select_related("parent", "edition__code")
        .filter(
            edition__code__code=code,
            edition__edition_id=edition_id,
            division=division or "",
            provision_id=provision_id,
        )
        .first()
    )
    if matched is None:
        return render(request, "partials/_viewer_section_content.html", empty_ctx)

    # Subtree root: the provision's parent so we render siblings + descendants.
    # When the provision is top-level, render itself + descendants.
    #
    # Bounded, like the permalink and by the same number.  This walk used to
    # have no limit at all, and a search result is not always a leaf article:
    # the candidate query does not exclude a version with an empty body, and
    # BM25F scores the title as its own field, so a part or a section can be
    # the match.  Its parent's subtree is then the 1,339-provision, 1.9 MB
    # render that ``CONTENTS_THRESHOLD`` exists to prevent — delivered inline,
    # with every body highlighted, on the one surface that had no cap.
    #
    # The context narrows before the panel changes character.  The parent is
    # here to give the match its siblings, but the reader searched for one
    # provision and must still be shown it, so the overlay gives up the
    # siblings first.  Only when the match's *own* subtree is too big does the
    # panel become a table of contents — the permalink's behaviour, from the
    # permalink's builder, so a reader who meets the contents of Part 9 here
    # and again on its own page meets one list.
    #
    # ``subtree_root`` moves with the walk.  The section list below descends
    # from it, and a root naming a provision no longer in ``all_provisions``
    # renders an empty panel.
    subtree_root = matched.parent or matched
    all_provisions, oversized = walk_subtree(
        subtree_root, edition=matched.edition, division=matched.division
    )
    if oversized and subtree_root.pk != matched.pk:
        subtree_root = matched
        all_provisions, oversized = walk_subtree(
            matched, edition=matched.edition, division=matched.division
        )
    if oversized:
        subtree_root = matched
        all_provisions = [matched]

    versions = in_force_versions(all_provisions, query_date)

    # Highlight the parsed query keywords in each in-force version body
    # (parity with the results-card highlight in api.formatters). Mutates the
    # in-memory html field only — these instances are never saved.
    if match_terms:
        for v in versions:
            if v.html:
                v.html = highlight_terms(v.html, match_terms)

    # Group versions by provision pk.
    by_provision: dict[int, list[CodeEditionProvisionVersion]] = {}
    for v in versions:
        by_provision.setdefault(v.provision_id, []).append(v)

    # Too big to show: the panel lists what is inside instead, through the
    # same builder and the same partial the permalink uses.  Built here rather
    # than beside the walk because the rows are scoped to the versions
    # overlapping the one on screen, which is not known until the in-force
    # filter above has run.  A match with nothing in force on this date has no
    # such version, and then the panel says only that.
    contents_ctx: dict[str, Any] = {
        "contents": [], "contents_total": 0, "contents_noun": "",
    }
    if oversized and by_provision.get(matched.pk):
        contents_ctx = contents_view(
            matched,
            by_provision[matched.pk][-1],
            matched.edition.code_name,
            matched.division,
        )

    # The reading ledger.  This partial renders the matched provision *and*
    # every descendant as a flat visible list, so it is a bulk text delivery
    # exactly like a permalink and is recorded the same way.  Unguarded by
    # HX-Request, unlike the engagement event below: that event measures a
    # deliberate click, while this records what left the server, and text
    # delivered to a refreshed URL left the server just the same.
    delivered, recorded = record_versions(request, versions)

    # Engagement: the user drilled into this provision from search results.
    # Pin the event to the version in force on the query date (the last one
    # grouped for the matched provision), attributed to the originating search
    # via ``search_id`` threaded through from the results partial.  Non-fatal.
    #
    # Only count genuine HTMX drill-ins.  This partial is always loaded via
    # htmx; a request without the ``HX-Request`` header is a crawler, a link
    # prefetch, or a direct/refreshed URL hit — counting those inflates the
    # click-through metric with views the user never initiated.
    if request.headers.get("HX-Request") == "true":
        matched_active = by_provision.get(matched.pk, [])
        record_event(
            request,
            event_type=EngagementEvent.EventType.PROVISION_VERSION_VIEW,
            object_type="CodeEditionProvisionVersion",
            object_id=matched_active[-1].pk if matched_active else None,
            search_id=_query_value(request, "search_id"),
            context={
                "code": code,
                "edition_id": edition_id,
                "division": matched.division,
                "provision_id": matched.provision_id,
                "query_date": query_date.isoformat(),
                "surface": "search_viewer",
                # What this response handed over, and what reached the ledger.
                # ``ledger_health`` compares whole days, so a page that
                # delivers forty texts and records three passes it; these two
                # make that visible per request.  This surface needs the check
                # most — it is the one that still renders a subtree inline.
                #
                # Recorded on the HX-guarded event while the ledger write above
                # is unguarded, so a non-HTMX request writes ledger rows that
                # no event describes.  The check reads events, so those are
                # invisible to it rather than counted as a shortfall.
                "delivered": delivered,
                "recorded": recorded,
            },
        )

    # Build depth-first ordered list rooted at subtree_root.
    by_pk: dict[int, CodeEditionProvision] = {p.pk: p for p in all_provisions}
    children_by_parent: dict[int | None, list[CodeEditionProvision]] = {}
    for prov in all_provisions:
        children_by_parent.setdefault(prov.parent_id, []).append(prov)
    for group in children_by_parent.values():
        group.sort(key=lambda p: code_order_key(p.provision_id))

    sections: list[dict[str, Any]] = []
    transition_active = False

    def _walk(parent_pk: int | None) -> None:
        nonlocal transition_active
        for prov in children_by_parent.get(parent_pk, []):
            active_for_prov = by_provision.get(prov.pk, [])
            if len(active_for_prov) > 1:
                transition_active = True
            sections.append({
                "provision_id": prov.provision_id,
                "node_id": prov.provision_id,  # legacy alias for templates
                "title": (
                    active_for_prov[-1].title
                    if active_for_prov else prov.provision_id
                ),
                "division": prov.division,
                "active_versions": active_for_prov,
                "is_active": prov.pk == matched.pk,
            })
            _walk(prov.pk)

    _walk(subtree_root.parent_id)
    # If the subtree_root itself wasn't picked up (top-level case), include it.
    if not any(s["provision_id"] == subtree_root.provision_id for s in sections):
        active_for_root = by_provision.get(subtree_root.pk, [])
        if len(active_for_root) > 1:
            transition_active = True
        sections.insert(0, {
            "provision_id": subtree_root.provision_id,
            "node_id": subtree_root.provision_id,
            "title": (
                active_for_root[-1].title
                if active_for_root else subtree_root.provision_id
            ),
            "division": subtree_root.division,
            "active_versions": active_for_root,
            "is_active": subtree_root.pk == matched.pk,
        })

    del by_pk  # only built for potential future use
    return render(
        request,
        "partials/_viewer_section_content.html",
        {
            "sections": sections,
            "active_node_id": provision_id,
            "active_provision_id": provision_id,
            "transition_active": transition_active,
            "query_date": query_date.isoformat(),
            **contents_ctx,
        },
    )


def _result_keys(cards: list[dict[str, Any]]) -> list[tuple[str, str, str, int]]:
    """Ledger keys for the result cards that carry a body.

    A card with no ``html_content`` delivered nothing to copy — a container
    heading, or a locked row where the gate did its job — and recording it
    would inflate coverage with text the reader never received.
    """
    keys: list[tuple[str, str, str, int]] = []
    for card in flatten(cards):
        if not (card.get("html_content") or "").strip():
            continue
        edition = str(card.get("code_edition") or card.get("code") or "")
        version = card.get("version")
        provision_id = str(card.get("id") or "")
        if not edition or not provision_id or version is None:
            continue
        keys.append((
            edition, str(card.get("division") or ""), provision_id, version.version,
        ))
    return keys


def _teaser_context(result: dict[str, Any]) -> dict[str, Any]:
    """Context for a search that ran but whose text is withheld.

    The visitor has spent the day's full-result allowance.  Rather than a page
    that says only "limit reached", they get the shape of the answer: how many
    provisions matched, in which editions, and what those provisions are
    called.  That is enough to tell them the corpus holds their answer, which
    is the one thing a generic wall can never say — and it is the honest basis
    for asking them to make an account.

    Identity rows come from ``identity_preview``, the same function that builds
    the free-tier locked list, so the two teasers cannot drift apart on screen.
    """
    results = result.get("results") or []
    locked_editions = result.get("locked_editions") or {}
    accessible = result.get("accessible_match_count", 0)
    # Bound once and reused below.  It was called three times for the three
    # figures it feeds, and this adds a fourth reader (the acknowledgement).
    preview = identity_preview(results)
    return {
        "success": True,
        "teaser_only": True,
        "results": [],
        "teaser_rows": [
            {**row, "edition_name": edition_display_name(row["code_edition"])}
            for row in preview
        ],
        # A teaser withholds the body and still prints titles, which are
        # legislative text, so the acknowledgement is owed here too.  The
        # editions named are the ones this page actually shows.
        "crown_years": crown_years_for_editions(
            [row["code_edition"] for row in preview] + list(locked_editions)
        ),
        # Counts the whole match set, not the previewed slice — the preview is
        # capped and the count is not, so they are different numbers and the
        # template says so with the "and N more" tail.
        "teaser_match_count": accessible + sum(locked_editions.values()),
        "teaser_row_remainder": max(0, accessible - len(preview)),
        "teaser_edition_counts": [
            {"name": edition_display_name(code), "count": count}
            for code, count in sorted(_teaser_edition_counts(results, locked_editions).items())
        ],
        "query_date": result.get("parsed_params", {}).get("date"),
        "keywords": result.get("parsed_params", {}).get("keywords", []),
        # Lets an edition request filed from this page join back to the query
        # that prompted it — "they asked for X after searching Y" is a stronger
        # signal than either fact alone.
        "search_id": result.get("search_history_id"),
        "signup_url": "/accounts/signup/",
        "login_url": "/accounts/login/",
    }


def _teaser_edition_counts(
    results: list[dict[str, Any]], locked_editions: dict[str, int]
) -> dict[str, int]:
    """Per-edition match counts across both sides of the tier split.

    The rate-limit teaser is not a tier teaser: the visitor is blocked by the
    day's allowance, not by their plan, so an edition they *could* have read
    and one they could not are withheld for the same reason right now and
    belong in one list.
    """
    counts: dict[str, int] = dict(locked_editions)
    for row in results:
        name = row.get("code_edition", "")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


@require_POST
def search_results(request):
    """HTMX search results view."""
    query = request.POST.get("query", "")
    date_override = request.POST.get("date")
    province_override = request.POST.get("province")

    # The relevance-floor control posts back through this same view, so moving
    # the line re-runs the query rather than needing a second endpoint.
    match_threshold = resolve_match_threshold(request)

    # What the reader has told us about their building.  Ranking only: it
    # prefers the part the code says governs such a building, and none of it
    # reaches the scored keywords.
    building = _building_from(request.POST)
    # Whether the reader named an occupancy themselves.  Read here because
    # ``building`` is reassigned below to the *effective* one, which carries
    # the parser's reading too and so can never answer this question.
    reader_chose_occupancy = bool(building.get("occupancy"))

    # A new search, or a re-measure of the one already on screen.  Only the
    # relevance-floor control can tell us: its field lives in the results
    # partial, and it re-posts without the reader touching the form.  The
    # building fields deliberately do NOT count — they sit in the search form
    # now, so every search posts them and testing for their presence would
    # make every search look like a re-measure and stop writing history
    # entries altogether.  A reader who changes the building and presses
    # Search has run a search, and the address they land on differs, so an
    # entry there is a real place for Back to return to.
    refining = "match_threshold" in request.POST

    # Extract IP for anonymous tracking
    ip = extract_client_ip(request.META)

    result = run_search(
        query,
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        date_override=date_override or None,
        province_override=province_override or None,
        match_threshold=match_threshold,
        building=building,
    )

    if not result["success"]:
        return render(
            request,
            "partials/search_results_partial.html",
            {
                "success": False,
                "error": result["error"],
                # Present -> render the date-specific validation message and
                # echo the bad value back to the user (see the partial).
                "invalid_date": result.get("invalid_date"),
            },
        )

    # What the search actually ranked by — the reader's corrections *and* the
    # parser's own reading of the query, which is what the address must name
    # and what the control must draw.  Read back out of the parse rather than
    # from the post, or a first search whose occupancy the model supplied
    # would rank one way and hand out a link that ranks another.
    building = _building_from(result.get("parsed_params") or {})

    # Band 2 of the anonymous allowance (core.middleware): the search ran, but
    # the text is withheld.  Returns before the full context is built — the
    # teaser needs six values, and threading a "hide everything" flag through
    # the ninety-line context below would put the withholding decision in the
    # template, where every future key would have to remember it.
    if getattr(request, "search_teaser_only", False):
        # The address is pushed here too.  The search ran; only the text was
        # withheld.  A reader who signs in and reloads gets their own search
        # answered, rather than having to remember and retype it.
        teaser = render(
            request, "partials/search_results_partial.html", _teaser_context(result)
        )
        _push_search_url(
            teaser, query, date_override, replace=refining, building=building
        )
        return _announce_parsed_occupancy(
            teaser, reader_chose=reader_chose_occupancy, building=building
        )

    # The search turned up results this user's tier can't open.  Recorded as an
    # *impression* (surface="search_results") rather than an attempt: the locked
    # editions render as a count, not as clickable rows, so this is the only
    # place most free users ever meet the gate — the other locked_content_view
    # surfaces need a permalink or a cross-edition link to reach.  One row per
    # search, carrying the per-edition counts, attributed to the search itself
    # so a later report can join demand (query) to what was withheld.
    locked_editions = result.get("locked_editions") or {}

    # What to call the things being counted.  Two nouns, not one, because the
    # two counts can be measured differently in the same render: under the
    # weak-match fallback the shown results are explicitly *not* close, while
    # the locked count on the other side of the gate still cleared the floor.
    # Calling both "close matches" there would contradict the fallback notice
    # sitting between them.
    floor_active = bool(result.get("match_threshold"))
    shown_is_close = floor_active and not result.get("weak_matches_only")
    shown_noun, shown_noun_suffix = (
        ("close match", "es") if shown_is_close else ("result", "s")
    )
    locked_noun, locked_noun_suffix = (
        ("close match", "es") if floor_active else ("result", "s")
    )

    # The header reads "N OF M" only when the render cap actually holds
    # something back.  Below the cap nothing is hidden, so claiming "43 OF 85"
    # would invite the reader to hunt for 42 results that were never withheld —
    # that form used to mean page-size truncation, which no longer exists.
    matched = result.get("accessible_match_count", 0)
    cap_binds = bool(result.get("cap_binds"))

    if locked_editions:
        record_event(
            request,
            event_type=EngagementEvent.EventType.LOCKED_CONTENT_VIEW,
            object_type="CodeEdition",
            search_id=result.get("search_history_id"),
            context={
                "surface": "search_results",
                "locked_editions": locked_editions,
                "locked_count": sum(locked_editions.values()),
                "shown_count": len(result["results"]),
            },
        )

    # The reading ledger.  A results page is not a map: every card carries the
    # provision's body, up to ``SEARCH_RESULT_CAP`` of them in one response, so
    # a search is one of the larger text deliveries in the product and has to
    # be recorded as one.
    #
    # ``flatten`` because the page's grouping shapes are presentation, not
    # identity: a parent-and-children card prints the parent's number over the
    # top child's text, and recording it as the parent would file the wrong
    # provision.  Its parts go in instead, and both sides of a transition pair
    # go in, because both texts were delivered.
    record_reads(request, _result_keys(result.get("results") or []))

    response = render(
        request,
        "partials/search_results_partial.html",
        {
            "success": True,
            "results": result["results"],
            # Echoed back so the CSV form can re-post the search that produced
            # this list.  The raw query, not the parsed parameters: the export
            # re-runs the pipeline rather than exporting a snapshot, so it must
            # be handed the same input, and the relevance floor is read from
            # the reader's own stored preference at the other end.
            "export_query": query,
            "export_date": date_override or "",
            "export_province": province_override or "",
            # The regulations that enacted the text on this page.  Taken from
            # the version behind each card, not from its edition: a provision
            # amended in 2024 sits in OBC 2012, and naming 2012 would credit
            # the wrong instrument by twelve years.
            #
            # The locked previews are a different case — they print titles for
            # editions this reader cannot open, and the card set carries no
            # version for them, so those fall back to the edition year.
            "crown_years": merge_years(
                crown_years_for_provisions(
                    card.get("provision") for card in flatten(result["results"])
                ),
                crown_years_for_editions(locked_editions or {}),
            ),
            "meta": {"applicable_codes": result["applicable_codes"]},
            # Same editions as meta.applicable_codes, as prose. The meta key
            # keeps the raw code_names because the JSON API publishes them;
            # the page renders these.
            "applicable_code_names": [
                edition_display_name(code) for code in result["applicable_codes"]
            ],
            "query_date": result.get("parsed_params", {}).get("date"),
            "keywords": result.get("parsed_params", {}).get("keywords", []),
            # What the search ranked by, as a reading.  The control itself
            # is in the search form, which this swap does not re-render, so
            # none of its inputs belong in this context.
            "building": building,
            "building_label": OCCUPANCY_SHORT.get(building.get("occupancy", "")),
            # The reader's own figure in the reader's own unit, resolved here
            # so the chip needs no unit map of its own.  Not ``area_m2``: that
            # is our conversion of what they typed, and the control, the
            # address and this reading should all show the same number.
            "building_area": (
                f"{building['area']:g} {AREA_UNITS[building['area_unit']]}"
                if building.get("area") else ""
            ),
            # One sentence, written once, so the hover and the modal cannot
            # drift apart — same rule as ``match_threshold_help`` above.
            #
            # It does NOT promise that the list is unchanged.  The boost is
            # applied before the relevance floor, so a demoted result whose
            # score falls under the reader's line does leave the page.  That
            # ordering is deliberate — the floor and the ranking must be
            # measured the same way — so the copy has to be honest about it
            # rather than the pipeline being bent to fit a slogan.
            "building_help": (
                "The code applies different parts to different buildings. "
                "This is the building we ranked for: the part that governs it "
                "is scored higher, and the parts that do not are scored lower. "
                "Change it in the search bar above."
            ),
            # Threaded into the viewer's section-content request so a
            # provision drill-in attributes back to this search.
            "search_id": result.get("search_history_id"),
            # Limitation notices detected from the query: a jurisdiction we
            # don't cover yet (results still shown for Ontario), or an
            # explicitly-named date outside coverage (no results — see partial).
            "not_covered_province": result.get("not_covered_province"),
            "date_out_of_range": result.get("date_out_of_range"),
            # Free-tier teaser, resolved to prose here rather than in the
            # template: the raw code_name ("OBC_2012") is an internal join key
            # and must not reach the page.
            "locked_edition_counts": [
                {"name": edition_display_name(code), "count": count}
                for code, count in sorted(locked_editions.items())
            ],
            "locked_count": sum(locked_editions.values()),
            "locked_preview": [
                {**row, "edition_name": edition_display_name(row["code_edition"])}
                for row in result.get("locked_preview") or []
            ],
            # Drives the "and N more" tail under the preview list.
            "locked_preview_remainder": max(
                0, sum(locked_editions.values()) - len(result.get("locked_preview") or [])
            ),
            "accessible_match_count": matched,
            # Only true when the render cap held something back; the header
            # switches to "N OF M" and explains itself on hover just here.
            "cap_binds": cap_binds,
            # Deliberately does not call the left-hand number "the N strongest
            # matches": it counts cards, and the formatter nests child
            # provisions under a parent card, so cards and matches are not the
            # same unit. Says what each number is instead of equating them.
            "cap_help": (
                f"This search matched {matched}, and one search renders at "
                f"most {SEARCH_RESULT_CAP} cards — the weakest are left off. "
                "Raise where close matches start, or narrow the search, to "
                "get a list you can read all of."
            ) if cap_binds else "",
            # Relevance-floor control. The reader drags a line across the
            # query's own score distribution rather than picking a named tier,
            # because a fixed cutoff isn't a fixed idea of closeness — 0.8
            # returns 20 results on one query and 1 on another. Everything the
            # control needs to redraw itself locally rides in one JSON blob.
            "match_threshold": result.get("match_threshold"),
            "weak_matches_only": result.get("weak_matches_only", False),
            "datum": {
                "buckets": result.get("score_buckets") or [],
                "width": result.get("score_bucket_width") or SCORE_BUCKET_WIDTH,
                "threshold": result.get("match_threshold"),
                "default": CLOSE_MATCH_THRESHOLD,
                # The server's exact count above the line at the resting
                # threshold. The control estimates from buckets while dragging,
                # but at rest it must agree to the unit. Deliberately *not*
                # accessible_match_count: when the weak-match fallback fires
                # that number is the whole list, and the control would claim
                # hundreds kept while drawing every bar as dropped.
                "keptExact": result.get("close_match_count", 0),
            },
            "shown_noun": shown_noun,
            "shown_noun_suffix": shown_noun_suffix,
            "locked_noun": locked_noun,
            "locked_noun_suffix": locked_noun_suffix,
            # One sentence, defined once: it names the active floor, so it
            # can't drift from the control beside it.
            "match_threshold_help": (
                f"Close matches score at least {result.get('match_threshold')}; "
                "every result prints its own score. Everything counted here, "
                "including the Pro total, is measured from that line. "
                "Click to move it."
            ),
        },
    )
    _push_search_url(
        response, query, date_override, replace=refining, building=building
    )
    return _announce_parsed_occupancy(
        response, reader_chose=reader_chose_occupancy, building=building
    )
