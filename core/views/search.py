"""Search-related views."""

from datetime import date
from typing import Any

from coloured_logger import Logger
from django.db.models import F, Q
from django.http import HttpRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from api.formatters import _code_order_key, highlight_terms
from config.code_metadata import (
    get_code_display_name,
    get_download_url,
    get_pdf_filename,
    get_source_url,
)
from core.events import record_event
from core.ip_utils import extract_client_ip
from core.models import (
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    EngagementEvent,
)

logger = Logger(__name__)


def _query_value(request: HttpRequest, key: str) -> str:
    value = request.GET.get(key)
    return value if isinstance(value, str) else ""



def _build_viewer_url_params(
    *,
    code_name: str,
    node_id: str,
    query_date: str,
    query_code: str,
    preferred_division: str = "",
) -> dict[str, Any] | None:
    """Build viewer-link parameters for ``node_id`` in ``code_name``.

    Queries the provenance schema directly.  If the provision exists in
    multiple divisions of the same edition (rare — only happens when
    the same ID is reused across Division A/B/C/D), prefer the
    caller's division, then body divisions over appendices.
    """
    if "_" not in code_name:
        return None
    system_code, edition_id = code_name.split("_", 1)
    edition = (
        CodeEdition.objects.select_related("code")
        .filter(code__code=system_code, edition_id=edition_id)
        .first()
    )
    if not edition:
        return None

    candidates = list(
        CodeEditionProvision.objects
        .filter(edition=edition, provision_id=node_id)[:5]
    )
    if not candidates:
        return None

    def _pick(divisions: list[str]) -> CodeEditionProvision | None:
        for d in divisions:
            for c in candidates:
                if c.division == d:
                    return c
        return None

    preferred = []
    if preferred_division:
        preferred.append(preferred_division)
    preferred.extend(["B", "C", "D", "A", ""])
    provision = _pick(preferred) or candidates[0]

    # Latest version's title is the most informative for a navigation
    # label (the user's effective query date doesn't matter here).
    latest_version = (
        provision.versions.order_by("-version").first()
    )
    title = latest_version.title if latest_version else node_id

    return {
        "id": provision.provision_id,
        "provision_id": provision.provision_id,
        "title": title,
        "code": code_name,
        "code_display_name": (
            f"{get_code_display_name(edition.code.code)} {edition.edition_id}".strip()
        ),
        "edition_id": edition.edition_id,
        "division": provision.division,
        "pdf_filename": get_pdf_filename(code_name, "") or "",
        "pdf_download_url": get_download_url(code_name) or "",
        "source_url": get_source_url(code_name) or "",
        "query_date": query_date,
        "query_code": query_code,
    }


def _build_viewer_navigation(
    current_code: str,
    node_id: str,
    query_date: str,
    query_code: str,
    preferred_division: str = "",
) -> dict[str, dict[str, Any] | None]:
    if not current_code or "_" not in current_code:
        return {"previous": None, "next": None}

    system_code, edition_id = current_code.split("_", 1)
    current_edition = (
        CodeEdition.objects.select_related("code")
        .filter(code__code=system_code, edition_id=edition_id)
        .first()
    )
    if not current_edition:
        return {"previous": None, "next": None}

    editions = list(
        CodeEdition.objects.select_related("code")
        .filter(code=current_edition.code)
        .order_by("effective_date", "year", "edition_id")
    )
    current_index = next(
        (index for index, edition in enumerate(editions) if edition.pk == current_edition.pk), None
    )
    if current_index is None:
        return {"previous": None, "next": None}

    previous_params = None
    next_params = None
    if current_index > 0:
        previous_params = _build_viewer_url_params(
            code_name=editions[current_index - 1].code_name,
            node_id=node_id,
            query_date=query_date,
            query_code=query_code,
            preferred_division=preferred_division,
        )
    if current_index < len(editions) - 1:
        next_params = _build_viewer_url_params(
            code_name=editions[current_index + 1].code_name,
            node_id=node_id,
            query_date=query_date,
            query_code=query_code,
            preferred_division=preferred_division,
        )
    return {"previous": previous_params, "next": next_params}


def home(request):
    """Main search page."""
    initial_query = request.GET.get("q", "")
    return render(request, "search.html", {"initial_query": initial_query})


def viewer_edition_nav(request: HttpRequest):
    """HTMX partial: edition navigation for the client-side viewer overlay."""
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
    navigation = _build_viewer_navigation(
        code, node_id, query_date, query_code, preferred_division=division,
    )
    return render(
        request,
        "partials/_viewer_edition_nav.html",
        {
            "previous_version": navigation["previous"],
            "next_version": navigation["next"],
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
            # Legacy field kept for template compatibility; will drop with
            # the load_maps cleanup card.
            edition_info["superseded_date"] = edition_info["ineffective_date"]
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


@require_POST
def search_results(request):
    """HTMX search results view."""
    query = request.POST.get("query", "")
    date_override = request.POST.get("date")
    province_override = request.POST.get("province")

    # Extract IP for anonymous tracking
    ip = extract_client_ip(request.META)

    from services.search_service import run_search

    result = run_search(
        query,
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        date_override=date_override or None,
        province_override=province_override or None,
    )

    if not result["success"]:
        return render(
            request,
            "partials/search_results_partial.html",
            {"success": False, "error": result["error"]},
        )

    return render(
        request,
        "partials/search_results_partial.html",
        {
            "success": True,
            "results": result["results"],
            "meta": {"applicable_codes": result["applicable_codes"]},
            "query_date": result.get("parsed_params", {}).get("date"),
            "keywords": result.get("parsed_params", {}).get("keywords", []),
            # Threaded into the viewer's section-content request so a
            # provision drill-in attributes back to this search.
            "search_id": result.get("search_history_id"),
        },
    )
