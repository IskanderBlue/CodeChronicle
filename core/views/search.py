"""Search-related views."""

from typing import Any

from coloured_logger import Logger
from django.http import HttpRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from config.code_metadata import (
    get_code_display_name,
    get_download_url,
    get_pdf_filename,
    get_source_url,
)
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


def _build_viewer_result_from_query(request: HttpRequest) -> dict[str, Any]:
    return {
        "id": _query_value(request, "id"),
        "title": _query_value(request, "title") or "No title",
        "code": _query_value(request, "code"),
        "code_display_name": _query_value(request, "code_display_name"),
        "map_code": _query_value(request, "map_code"),
        "page": _parse_optional_int(_query_value(request, "page")),
        "page_end": _parse_optional_int(_query_value(request, "page_end")),
        "initial_page_top": _parse_optional_float(_query_value(request, "initial_page_top")),
        "final_page_bottom": _parse_optional_float(_query_value(request, "final_page_bottom")),
        "pdf_filename": _query_value(request, "pdf_filename"),
        "pdf_download_url": _query_value(request, "pdf_download_url"),
        "source_url": _query_value(request, "source_url"),
        "query_date": _query_value(request, "query_date"),
        "query_code": _query_value(request, "query_code"),
        "result_type": None,
        "group_type": None,
        "amendments": [],
        "html_content": None,
        "notes_html": None,
    }


def _build_viewer_url_params(
    *, code_name: str, node_id: str, query_date: str, query_code: str
) -> dict[str, Any] | None:
    if "_" not in code_name:
        return None
    system_code, edition_id = code_name.split("_", 1)
    edition = (
        CodeEdition.objects.select_related("system")
        .filter(system__code=system_code, edition_id=edition_id)
        .first()
    )
    if not edition:
        return None

    node = (
        CodeMapNode.objects.filter(code_map__map_code__in=edition.map_codes, node_id=node_id)
        .select_related("code_map")
        .first()
    )
    if not node:
        return None

    map_code = node.code_map.map_code
    pdf_filename = get_pdf_filename(code_name, map_code) or ""
    return {
        "id": node.node_id,
        "title": node.title,
        "code": code_name,
        "code_display_name": f"{get_code_display_name(edition.system.code)} {edition.edition_id}".strip(),
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
    current_code: str, node_id: str, query_date: str, query_code: str
) -> dict[str, dict[str, Any] | None]:
    if not current_code or "_" not in current_code:
        return {"previous": None, "next": None}

    system_code, edition_id = current_code.split("_", 1)
    current_edition = (
        CodeEdition.objects.select_related("system")
        .filter(system__code=system_code, edition_id=edition_id)
        .first()
    )
    if not current_edition:
        return {"previous": None, "next": None}

    editions = list(
        CodeEdition.objects.select_related("system")
        .filter(system=current_edition.system)
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
        )
    if current_index < len(editions) - 1:
        next_params = _build_viewer_url_params(
            code_name=editions[current_index + 1].code_name,
            node_id=node_id,
            query_date=query_date,
            query_code=query_code,
        )
    return {"previous": previous_params, "next": next_params}


def home(request):
    """Main search page."""
    initial_query = request.GET.get("q", "")
    return render(request, "search.html", {"initial_query": initial_query})


def viewer_mode(request: HttpRequest):
    """Full-page viewer mode for browsing beyond a returned result."""
    result = _build_viewer_result_from_query(request)
    navigation = _build_viewer_navigation(
        current_code=result["code"],
        node_id=result["id"],
        query_date=result["query_date"],
        query_code=result["query_code"] or result["code"],
    )
    return render(
        request,
        "viewer_mode.html",
        {
            "result": result,
            "query_date": result["query_date"],
            "query_code": result["query_code"] or result["code"],
            "current_code": result["code"],
            "previous_version": navigation["previous"],
            "next_version": navigation["next"],
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
        },
    )
