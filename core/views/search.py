"""Search-related views."""

from datetime import date
from typing import Any

from coloured_logger import Logger
from django.db.models import F, Q
from django.http import HttpRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from api.formatters import _code_order_key, highlight_terms
from api.search.orchestration import identity_preview
from config.code_metadata import edition_display_name, get_code_display_name
from config.search_limits import (
    CLOSE_MATCH_THRESHOLD,
    SCORE_BUCKET_WIDTH,
    SEARCH_RESULT_CAP,
)
from core.access import edition_allowed
from core.events import record_event
from core.ip_utils import extract_client_ip
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
)
from core.provision_lineage import LineageDirection, annotate_lineage_locks, resolve_lineage
from core.search_prefs import resolve_match_threshold
from core.seo import TITLE_SUFFIX
from services.search_service import run_search

logger = Logger(__name__)


def _query_value(request: HttpRequest, key: str) -> str:
    value = request.GET.get(key)
    return value if isinstance(value, str) else ""



def _lineage_nav_direction(
    direction: LineageDirection, titles: dict[int, str]
) -> dict[str, Any]:
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
            "title": titles.get(target.pk, target.provision_id),
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
            "example_queries": EXAMPLE_QUERIES,
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
        annotate_lineage_locks([lineage], request.user)
        # Latest version's title is the most informative for a navigation
        # label (the user's effective query date doesn't matter here);
        # ascending order so the last write per provision wins.
        target_pks = [
            link.provision.pk
            for d in (lineage.predecessors, lineage.successors)
            for link in d.links
        ]
        titles: dict[int, str] = {}
        for prov_pk, title in (
            CodeEditionProvisionVersion.objects
            .filter(provision_id__in=target_pks)
            .order_by("version")
            .values_list("provision_id", "title")
        ):
            if title:
                titles[prov_pk] = title
        predecessors = _lineage_nav_direction(lineage.predecessors, titles)
        successors = _lineage_nav_direction(lineage.successors, titles)

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


def _active_versions(
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
    subtree_root = matched.parent or matched

    # Gather siblings + all descendants via parent walk.
    all_provisions: list[CodeEditionProvision] = [subtree_root]
    frontier = [subtree_root.pk]
    while frontier:
        children = list(
            CodeEditionProvision.objects
            .filter(parent_id__in=frontier)
            .filter(edition=matched.edition, division=matched.division)
        )
        if not children:
            break
        all_provisions.extend(children)
        frontier = [c.pk for c in children]

    versions = _active_versions(all_provisions, query_date)

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
            },
        )

    # Build depth-first ordered list rooted at subtree_root.
    by_pk: dict[int, CodeEditionProvision] = {p.pk: p for p in all_provisions}
    children_by_parent: dict[int | None, list[CodeEditionProvision]] = {}
    for prov in all_provisions:
        children_by_parent.setdefault(prov.parent_id, []).append(prov)
    for group in children_by_parent.values():
        group.sort(key=lambda p: _code_order_key(p.provision_id))

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
        },
    )


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
    return {
        "success": True,
        "teaser_only": True,
        "results": [],
        "teaser_rows": [
            {**row, "edition_name": edition_display_name(row["code_edition"])}
            for row in identity_preview(results)
        ],
        # Counts the whole match set, not the previewed slice — the preview is
        # capped and the count is not, so they are different numbers and the
        # template says so with the "and N more" tail.
        "teaser_match_count": accessible + sum(locked_editions.values()),
        "teaser_row_remainder": max(0, accessible - len(identity_preview(results))),
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

    # Extract IP for anonymous tracking
    ip = extract_client_ip(request.META)

    result = run_search(
        query,
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        date_override=date_override or None,
        province_override=province_override or None,
        match_threshold=match_threshold,
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

    # Band 2 of the anonymous allowance (core.middleware): the search ran, but
    # the text is withheld.  Returns before the full context is built — the
    # teaser needs six values, and threading a "hide everything" flag through
    # the ninety-line context below would put the withholding decision in the
    # template, where every future key would have to remember it.
    if getattr(request, "search_teaser_only", False):
        return render(
            request,
            "partials/search_results_partial.html",
            _teaser_context(result),
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

    return render(
        request,
        "partials/search_results_partial.html",
        {
            "success": True,
            "results": result["results"],
            "meta": {"applicable_codes": result["applicable_codes"]},
            # Same editions as meta.applicable_codes, as prose. The meta key
            # keeps the raw code_names because the JSON API publishes them;
            # the page renders these.
            "applicable_code_names": [
                edition_display_name(code) for code in result["applicable_codes"]
            ],
            "query_date": result.get("parsed_params", {}).get("date"),
            "keywords": result.get("parsed_params", {}).get("keywords", []),
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
