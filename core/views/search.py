"""Search-related views."""

from typing import Any

from coloured_logger import Logger
from django.http import HttpRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from api.formatters import _code_order_key
from config.code_metadata import (
    get_code_display_name,
    get_download_url,
    get_pdf_filename,
    get_source_url,
)
from config.transitions import load_transitions
from core.ip_utils import extract_client_ip
from core.models import CodeEdition, CodeMapNode

logger = Logger(__name__)


def _parse_optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _query_value(request: HttpRequest, key: str) -> str:
    value = request.GET.get(key)
    return value if isinstance(value, str) else ""



def _build_viewer_url_params(
    *,
    code_name: str,
    node_id: str,
    query_date: str,
    query_code: str,
    preferred_map_code: str = "",
) -> dict[str, Any] | None:
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

    # Prefer the caller's map so navigation stays in the same PDF/volume.
    # When bare IDs match multiple divisions, prefer body sections (B > A).
    def _pick_best_node(qs):
        nodes = list(qs.select_related("code_map")[:5])
        if not nodes:
            return None
        if len(nodes) == 1:
            return nodes[0]
        # Prefer body divisions (B, C, D) over appendix (A) or empty
        for preferred in ("B", "C", "D", "A", ""):
            for n in nodes:
                if n.division == preferred:
                    return n
        return nodes[0]

    node = None
    if preferred_map_code and preferred_map_code in edition.map_codes:
        node = _pick_best_node(
            CodeMapNode.objects.filter(
                code_map__map_code=preferred_map_code, node_id=node_id
            )
        )
    if not node:
        node = _pick_best_node(
            CodeMapNode.objects.filter(
                code_map__map_code__in=edition.map_codes, node_id=node_id
            )
        )
    if not node:
        return None

    map_code = node.code_map.map_code
    pdf_filename = get_pdf_filename(code_name, map_code) or ""
    return {
        "id": node.node_id,
        "title": node.title,
        "code": code_name,
        "code_display_name": f"{get_code_display_name(edition.code.code)} {edition.edition_id}".strip(),
        "map_code": map_code,
        "page": node.page,
        "page_end": node.page_end,
        "initial_page_top": node.initial_page_top,
        "final_page_bottom": node.final_page_bottom,
        "pdf_filename": pdf_filename,
        "pdf_download_url": get_download_url(code_name) if pdf_filename else "",
        "source_url": get_source_url(code_name) or "",
        "query_date": query_date,
        "query_code": query_code,
    }


def _build_viewer_navigation(
    current_code: str,
    node_id: str,
    query_date: str,
    query_code: str,
    preferred_map_code: str = "",
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
            preferred_map_code=preferred_map_code,
        )
    if current_index < len(editions) - 1:
        next_params = _build_viewer_url_params(
            code_name=editions[current_index + 1].code_name,
            node_id=node_id,
            query_date=query_date,
            query_code=query_code,
            preferred_map_code=preferred_map_code,
        )
    return {"previous": previous_params, "next": next_params}


def home(request):
    """Main search page."""
    initial_query = request.GET.get("q", "")
    return render(request, "search.html", {"initial_query": initial_query})


def viewer_edition_nav(request: HttpRequest):
    """HTMX partial: edition navigation for the client-side viewer overlay."""
    code = _query_value(request, "code")
    node_id = _query_value(request, "node_id")
    query_date = _query_value(request, "query_date")
    query_code = _query_value(request, "query_code")
    map_code = _query_value(request, "map_code")
    navigation = _build_viewer_navigation(
        code, node_id, query_date, query_code, preferred_map_code=map_code
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
            edition_info["superseded_date"] = (
                edition.superseded_date.isoformat() if edition.superseded_date else None
            )
            edition_info["code_name"] = code
            edition_info["code_display_name"] = (
                f"{get_code_display_name(edition.code.code)} {edition.edition_id}".strip()
            )

            # Find any transition that gives this edition lingering validity
            transitions = []
            for record in load_transitions():
                if record["old_edition"] == code or record["new_edition"] == code:
                    transitions.append({
                        "old_edition": record["old_edition"],
                        "new_edition": record["new_edition"],
                        "overlap_start": record["overlap_start"],
                        "overlap_end": record["overlap_end"],
                        "transition_type": str(record["transition_type"]).replace("_", " "),
                    })
            edition_info["transitions"] = transitions

    return render(
        request,
        "partials/_viewer_edition_dates.html",
        {"edition": edition_info, "query_date": query_date},
    )


def viewer_section_content(request: HttpRequest):
    """HTMX partial: section HTML context for the viewer overlay."""
    map_code = _query_value(request, "map_code")
    node_id = _query_value(request, "node_id")

    if not map_code or not node_id:
        return render(request, "partials/_viewer_section_content.html",
                      {"sections": [], "active_node_id": node_id})

    # Find the matched node's parent_id and division
    matched = (
        CodeMapNode.objects.filter(code_map__map_code=map_code, node_id=node_id)
        .values("parent_id", "division")
        .first()
    )
    if not matched or not matched["parent_id"]:
        # No parent — just return the single node
        node = (
            CodeMapNode.objects.filter(code_map__map_code=map_code, node_id=node_id)
            .values("node_id", "title", "html", "notes_html")
            .first()
        )
        sections = [node] if node else []
        return render(request, "partials/_viewer_section_content.html",
                      {"sections": sections, "active_node_id": node_id})

    parent_id = matched["parent_id"]
    division = matched.get("division", "")
    div_filter: dict[str, str] = {"code_map__map_code": map_code}
    if division:
        div_filter["division"] = division

    # Collect full subtree: siblings + all descendants (tables hang off subclauses)
    siblings = list(
        CodeMapNode.objects.filter(parent_id=parent_id, **div_filter)
        .values("node_id", "title", "html", "notes_html", "parent_id")
    )

    # Recursively expand: fetch children of current frontier until exhausted
    all_nodes = list(siblings)
    frontier_ids = [s["node_id"] for s in siblings]
    while frontier_ids:
        children = list(
            CodeMapNode.objects.filter(
                parent_id__in=frontier_ids, **div_filter
            ).values("node_id", "title", "html", "notes_html", "parent_id")
        )
        if not children:
            break
        all_nodes.extend(children)
        frontier_ids = [c["node_id"] for c in children]

    # Build depth-first ordered tree using parent_id relationships
    children_by_parent: dict[str, list] = {}
    for node in all_nodes:
        pid = node.get("parent_id") or ""
        children_by_parent.setdefault(pid, []).append(node)
    for group in children_by_parent.values():
        group.sort(key=lambda n: _code_order_key(n["node_id"]))

    def _walk(pid: str) -> list:
        result = []
        for node in children_by_parent.get(pid, []):
            result.append(node)
            result.extend(_walk(node["node_id"]))
        return result

    sections = _walk(parent_id)

    return render(request, "partials/_viewer_section_content.html",
                  {"sections": sections, "active_node_id": node_id})


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
        },
    )
