"""
Format search results for frontend display.
"""

import re
from typing import Any, Dict, Iterable, List, Tuple

from config.code_metadata import (
    get_code_display_name,
    get_download_url,
    get_pdf_filename,
    get_source_url,
)
from core.models import CodeMapNode


def _build_code_display_name(code_edition: str) -> str:
    """Turn 'OBC_2024' into 'Ontario Building Code 2024'."""
    parts = code_edition.split("_", 1)
    prefix = parts[0]
    year = parts[1] if len(parts) > 1 else ""
    display = get_code_display_name(prefix)
    return f"{display} {year}".strip()


def _code_order_key(value: str) -> Tuple[Any, ...]:
    parts = re.split(r"(\d+)", value or "")
    key: list[Any] = []
    for part in parts:
        if not part:
            continue
        key.append(int(part) if part.isdigit() else part.lower())
    return tuple(key)


def _format_single_result(result: Dict[str, Any]) -> Dict[str, Any]:
    code_edition = result.get("code_edition", "Unknown")
    page = result.get("page")
    page_end = result.get("page_end", page)

    pdf_filename = ""
    map_code = result.get("map_code", "")
    if map_code:
        pdf_filename = get_pdf_filename(code_edition, map_code) or ""

    section_data = {
        "id": result.get("id"),
        "title": result.get("title", "No title"),
        "code": code_edition,
        "code_display_name": _build_code_display_name(code_edition),
        "map_code": map_code,
        "parent_id": result.get("parent_id"),
        "source_date": result.get("source_date"),
        "page": page,
        "page_end": page_end,
        "initial_page_top": result.get("initial_page_top"),
        "final_page_bottom": result.get("final_page_bottom"),
        "score": result.get("score", 0),
        "pdf_filename": pdf_filename,
        "pdf_download_url": get_download_url(code_edition) if pdf_filename else "",
        "html_content": result.get("html_content"),
        "notes_html": result.get("notes_html"),
        "source_url": get_source_url(code_edition),
        "group_type": None,
        "result_type": None,
        "transition_context": result.get("transition_context"),
    }
    section_data["amendments"] = get_amendments_for_section(
        str(result.get("id") or ""), code_edition
    )
    return section_data


def _build_group_lookup_key(result: Dict[str, Any]) -> tuple[str, str, str] | None:
    parent_id = result.get("parent_id")
    code = result.get("code")
    map_code = result.get("map_code")
    if not parent_id or not code or not map_code:
        return None
    return str(code), str(map_code), str(parent_id)


def _load_group_hierarchy(
    formatted_results: Iterable[Dict[str, Any]],
) -> Dict[tuple[str, str, str], Dict[str, Any]]:
    group_keys = {
        key for result in formatted_results if (key := _build_group_lookup_key(result)) is not None
    }
    hierarchy: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    for code_edition, map_code, parent_id in group_keys:
        parent_node = (
            CodeMapNode.objects.filter(code_map__map_code=map_code, node_id=parent_id)
            .values("node_id", "title")
            .first()
        )
        child_nodes = list(
            CodeMapNode.objects.filter(code_map__map_code=map_code, parent_id=parent_id).values(
                "node_id", "title", "page", "page_end"
            )
        )
        child_nodes.sort(key=lambda item: _code_order_key(str(item.get("node_id") or "")))
        hierarchy[(code_edition, map_code, parent_id)] = {
            "parent_title": (parent_node or {}).get("title") or parent_id,
            "children": child_nodes,
        }

    return hierarchy


def _build_grouped_result(
    matched_results: List[Dict[str, Any]],
    hierarchy: Dict[str, Any],
    group_key: tuple[str, str, str],
) -> Dict[str, Any] | None:
    if len(matched_results) <= 1:
        return None

    child_nodes = hierarchy.get("children") or []
    child_total_count = len(child_nodes)
    if child_total_count <= 1:
        return None

    matched_by_id = {str(item.get("id")): item for item in matched_results if item.get("id")}
    child_match_count = sum(
        1 for child in child_nodes if str(child.get("node_id")) in matched_by_id
    )
    if child_match_count <= 1:
        return None
    if (child_match_count / child_total_count) <= 0.8:
        return None

    top_scoring_child = max(
        matched_results,
        key=lambda item: (item.get("score", 0), -matched_results.index(item)),
    )
    parent_id = group_key[2]
    children = []
    for child in child_nodes:
        child_id = str(child.get("node_id"))
        matched = matched_by_id.get(child_id)
        children.append(
            {
                "id": child_id,
                "title": child.get("title") or child_id,
                "page": (matched or child).get("page"),
                "page_end": (matched or child).get("page_end"),
                "score": (matched or {}).get("score", 0),
                "is_match": matched is not None,
                "is_top_scoring": child_id == top_scoring_child.get("id"),
            }
        )

    grouped = dict(top_scoring_child)
    grouped.update(
        {
            "id": parent_id,
            "title": hierarchy.get("parent_title") or parent_id,
            "group_type": "parent_children",
            "parent_id": parent_id,
            "children": children,
            "top_scoring_child_id": top_scoring_child.get("id"),
            "active_child": {
                "id": top_scoring_child.get("id"),
                "title": top_scoring_child.get("title"),
            },
            "viewer_node_id": top_scoring_child.get("id"),
            "viewer_title": top_scoring_child.get("title"),
            "child_match_count": child_match_count,
            "child_total_count": child_total_count,
            "matched_child_ids": [item.get("id") for item in matched_results if item.get("id")],
        }
    )
    return grouped


def group_formatted_results(
    formatted_results: List[Dict[str, Any]],
    hierarchy_by_group: Dict[tuple[str, str, str], Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    if hierarchy_by_group is None:
        hierarchy_by_group = _load_group_hierarchy(formatted_results)

    matched_results_by_group: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
    for result in formatted_results:
        key = _build_group_lookup_key(result)
        if key is None:
            continue
        matched_results_by_group.setdefault(key, []).append(result)

    grouped_results_by_key: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for key, matched_results in matched_results_by_group.items():
        grouped = _build_grouped_result(matched_results, hierarchy_by_group.get(key, {}), key)
        if grouped is not None:
            grouped_results_by_key[key] = grouped

    collapsed_keys: set[tuple[str, str, str]] = set()
    output: List[Dict[str, Any]] = []
    for result in formatted_results:
        key = _build_group_lookup_key(result)
        if key in grouped_results_by_key:
            if key in collapsed_keys:
                continue
            output.append(grouped_results_by_key[key])
            collapsed_keys.add(key)
            continue
        output.append(result)

    return output


def merge_transition_compare_results(
    formatted_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    transition_groups: Dict[tuple[str, str, str], Dict[str, Dict[str, Any]]] = {}
    for result in formatted_results:
        transition_context = result.get("transition_context")
        if not transition_context or result.get("group_type") == "parent_children":
            continue
        key = (
            str(result.get("id") or ""),
            str(transition_context.get("new_edition") or ""),
            str(transition_context.get("old_edition") or ""),
        )
        edition = str(result.get("code") or "")
        transition_groups.setdefault(key, {})[edition] = result

    consumed_keys: set[tuple[str, str, str]] = set()
    output: List[Dict[str, Any]] = []
    for result in formatted_results:
        transition_context = result.get("transition_context")
        if not transition_context or result.get("group_type") == "parent_children":
            output.append(result)
            continue

        key = (
            str(result.get("id") or ""),
            str(transition_context.get("new_edition") or ""),
            str(transition_context.get("old_edition") or ""),
        )
        grouped_versions = transition_groups.get(key, {})
        if key in consumed_keys:
            continue

        new_version = grouped_versions.get(str(transition_context.get("new_edition") or ""))
        old_version = grouped_versions.get(str(transition_context.get("old_edition") or ""))
        if not new_version or not old_version:
            output.append(result)
            continue

        consumed_keys.add(key)
        output.append(
            {
                "id": result.get("id"),
                "title": new_version.get("title")
                or old_version.get("title")
                or result.get("title"),
                "code": new_version.get("code")
                or old_version.get("code")
                or result.get("code"),
                "code_display_name": new_version.get("code_display_name")
                or result.get("code_display_name"),
                "score": max(new_version.get("score", 0), old_version.get("score", 0)),
                "result_type": "transition_compare",
                "transition_context": transition_context,
                "versions": [new_version, old_version],
            }
        )

    return output


def format_search_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform raw search results into a format suitable for the frontend."""
    formatted = [_format_single_result(result) for result in results]
    formatted.sort(key=lambda item: item.get("score", 0), reverse=True)
    grouped = group_formatted_results(formatted)
    return merge_transition_compare_results(grouped)


def get_amendments_for_section(section_id: str, code_edition: str) -> List[Dict[str, Any]]:
    """Mock amendment lookup placeholder."""
    return []
