"""Search orchestration: execute_search and result deduplication."""

from datetime import date
from typing import Any, Dict, List

from coloured_logger import Logger

from config.code_metadata import get_applicable_codes, get_map_codes
from config.transitions import get_active_transitions
from core.models import CodeMapNode

from .engine import SEARCH_RESULT_LIMIT, _search_code_db

logger = Logger(__name__)


def _enrich_search_results(
    results: List[Dict[str, Any]],
    *,
    code_name: str,
    map_code: str,
    search_date: date,
) -> List[Dict[str, Any]]:
    initial_page_top_lookup: Dict[str, float] = {}
    final_page_bottom_lookup: Dict[str, float] = {}
    html_lookup: Dict[str, str] = {}
    notes_html_lookup: Dict[str, str] = {}
    parent_lookup: Dict[str, str] = {}
    division_lookup: Dict[str, str] = {}
    provision_transitions_lookup: Dict[str, list] = {}
    result_ids = [r.get("id") for r in results if r.get("id")]
    if result_ids:
        nodes = CodeMapNode.objects.filter(
            code_map__map_code=map_code,
            node_id__in=result_ids,
        ).values(
            "node_id",
            "initial_page_top",
            "final_page_bottom",
            "html",
            "notes_html",
            "parent_id",
            "division",
            "provision_transitions",
        )
        for node in nodes:
            node_id = node["node_id"]
            if node.get("initial_page_top") is not None:
                initial_page_top_lookup[node_id] = node["initial_page_top"]
            if node.get("final_page_bottom") is not None:
                final_page_bottom_lookup[node_id] = node["final_page_bottom"]
            if node.get("html"):
                html_lookup[node_id] = node["html"]
            if node.get("notes_html"):
                notes_html_lookup[node_id] = node["notes_html"]
            if node.get("parent_id"):
                parent_lookup[node_id] = node["parent_id"]
            division_lookup[node_id] = node.get("division", "")
            if node.get("provision_transitions"):
                provision_transitions_lookup[node_id] = node["provision_transitions"]

    enriched: List[Dict[str, Any]] = []
    for result in results:
        item = dict(result)
        item["code_edition"] = code_name
        item["map_code"] = map_code
        item["source_date"] = search_date.isoformat()
        item["initial_page_top"] = initial_page_top_lookup.get(result.get("id"))
        item["final_page_bottom"] = final_page_bottom_lookup.get(result.get("id"))
        item["html_content"] = html_lookup.get(result.get("id"))
        item["notes_html"] = notes_html_lookup.get(result.get("id"))
        item["parent_id"] = parent_lookup.get(result.get("id"))
        item["division"] = division_lookup.get(result.get("id"), result.get("division", ""))
        item["provision_transitions"] = provision_transitions_lookup.get(result.get("id"), [])
        enriched.append(item)
    return enriched


def _search_code_maps(
    *,
    code_name: str,
    map_codes: List[str],
    keywords: List[str],
    section_references: List[str],
    search_date: date,
) -> List[Dict[str, Any]]:
    all_results: List[Dict[str, Any]] = []
    for map_code in map_codes:
        try:
            search_response = _search_code_db(
                query=" ".join(keywords),
                map_code=map_code,
                limit=SEARCH_RESULT_LIMIT,
                section_references=section_references or None,
            )
            results = search_response.get("results", [])
            all_results.extend(
                _enrich_search_results(
                    results,
                    code_name=code_name,
                    map_code=map_code,
                    search_date=search_date,
                )
            )
        except Exception as exc:
            logger.error("Error searching %s (map=%s): %s", code_name, map_code, exc)
    return all_results


def _build_transition_context(record: Dict[str, Any], search_date: date) -> Dict[str, Any]:
    transition_type = str(record["transition_type"])
    return {
        "old_edition": record["old_edition"],
        "new_edition": record["new_edition"],
        "query_date": search_date.isoformat(),
        "new_version_effective_date": record["overlap_start"],
        "old_version_last_date": record["overlap_end"],
        "transition_type": transition_type,
        "transition_type_display": transition_type.replace("_", " "),
        "applicability_text": record["applicability_text"],
        "citation_text": record["citation_text"],
    }


def _supplement_transition_results(
    results: List[Dict[str, Any]],
    active_transitions: List[Dict[str, Any]],
    search_date: date,
) -> List[Dict[str, Any]]:
    """Add missing counterpart results so transition pairs can be formed.

    When a provision ID appears in one edition but not the other during a
    transition, look it up directly by node_id in the missing edition's maps.
    This prevents provisions from losing their comparison pair just because
    they fell outside the keyword search's top-N results.
    """
    if not active_transitions:
        return results

    by_code_and_id = {
        (item.get("code_edition"), item.get("id")): item for item in results
    }
    supplemented: List[Dict[str, Any]] = []

    for record in active_transitions:
        old_edition = record["old_edition"]
        new_edition = record["new_edition"]
        old_maps = get_map_codes(old_edition)
        new_maps = get_map_codes(new_edition)

        ids_in_new = {
            item.get("id")
            for item in results
            if item.get("code_edition") == new_edition and item.get("id")
        }
        ids_in_old = {
            item.get("id")
            for item in results
            if item.get("code_edition") == old_edition and item.get("id")
        }

        missing_in_old = ids_in_new - ids_in_old
        missing_in_new = ids_in_old - ids_in_new

        for missing_id, target_edition, target_maps in [
            (missing_in_old, old_edition, old_maps),
            (missing_in_new, new_edition, new_maps),
        ]:
            if not missing_id or not target_maps:
                continue
            for map_code in target_maps:
                nodes = CodeMapNode.objects.filter(
                    code_map__map_code=map_code,
                    node_id__in=list(missing_id),
                ).values(
                    "node_id", "title", "page", "page_end",
                    "initial_page_top", "final_page_bottom",
                    "html", "notes_html", "parent_id",
                    "division", "provision_transitions",
                )
                for node in nodes:
                    node_id = node["node_id"]
                    key = (target_edition, node_id)
                    if key in by_code_and_id:
                        continue
                    item = {
                        "id": node_id,
                        "title": node.get("title") or node_id,
                        "page": node.get("page"),
                        "page_end": node.get("page_end"),
                        "score": 0.0,
                        "code_edition": target_edition,
                        "map_code": map_code,
                        "source_date": search_date.isoformat(),
                        "initial_page_top": node.get("initial_page_top"),
                        "final_page_bottom": node.get("final_page_bottom"),
                        "html_content": node.get("html"),
                        "notes_html": node.get("notes_html"),
                        "parent_id": node.get("parent_id"),
                        "division": node.get("division", ""),
                        "provision_transitions": node.get("provision_transitions") or [],
                    }
                    by_code_and_id[key] = item
                    supplemented.append(item)

    if supplemented:
        logger.info(
            "Supplemented %d transition counterpart(s): %s",
            len(supplemented),
            [f"{s['code_edition']}:{s['id']}" for s in supplemented],
        )
        return results + supplemented
    return results


def _apply_transition_pairs(
    results: List[Dict[str, Any]],
    active_transitions: List[Dict[str, Any]],
    search_date: date,
) -> List[Dict[str, Any]]:
    by_code_and_id = {(item.get("code_edition"), item.get("id")): item for item in results}
    for record in active_transitions:
        transition_context = _build_transition_context(record, search_date)
        shared_ids = {
            item.get("id")
            for item in results
            if item.get("code_edition") in {record["old_edition"], record["new_edition"]}
        }
        for result_id in shared_ids:
            new_item = by_code_and_id.get((record["new_edition"], result_id))
            old_item = by_code_and_id.get((record["old_edition"], result_id))
            if not new_item or not old_item:
                continue
            new_item["transition_context"] = {**transition_context, "is_primary": True}
            old_item["transition_context"] = {**transition_context, "is_primary": False}
    return results


def execute_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute search based on parsed parameters."""
    search_date_str = params.get("date")
    keywords = params.get("keywords", [])
    province = params.get("province", "ON")
    section_references = params.get("section_references", [])

    try:
        search_date = date.fromisoformat(search_date_str)
    except (ValueError, TypeError):
        search_date = date.today()

    applicable_codes = get_applicable_codes(province, search_date)
    if not applicable_codes:
        return {"error": f"No building codes found for {province} on {search_date}", "results": []}

    all_results: List[Dict[str, Any]] = []

    for code_name in applicable_codes:
        map_codes = get_map_codes(code_name)
        if not map_codes:
            logger.warning("No map codes configured for %s, skipping", code_name)
            continue
        all_results.extend(
            _search_code_maps(
                code_name=code_name,
                map_codes=map_codes,
                keywords=keywords,
                section_references=section_references,
                search_date=search_date,
            )
        )

    active_transitions = get_active_transitions(applicable_codes, search_date)
    whole_code_transitions = [
        t for t in active_transitions if t.get("scope", "whole_code") == "whole_code"
    ]
    for transition in whole_code_transitions:
        old_code_name = transition["old_edition"]
        map_codes = get_map_codes(old_code_name)
        if not map_codes:
            logger.warning(
                "No map codes configured for transition edition %s, skipping", old_code_name
            )
            continue
        all_results.extend(
            _search_code_maps(
                code_name=old_code_name,
                map_codes=map_codes,
                keywords=keywords,
                section_references=section_references,
                search_date=search_date,
            )
        )

    unique_results = deduplicate_results(all_results)
    unique_results = _supplement_transition_results(
        unique_results, whole_code_transitions, search_date
    )
    unique_results = _apply_transition_pairs(unique_results, whole_code_transitions, search_date)

    top_results_metadata = []
    for result in unique_results[:SEARCH_RESULT_LIMIT]:
        top_results_metadata.append(
            {
                "code": result.get("code_edition", "Unknown"),
                "year": result.get("source_date", "")[:4],
                "section_id": result.get("id", ""),
                "title": result.get("title", "Untitled Provision"),
            }
        )

    return {
        "applicable_codes": applicable_codes,
        "results": unique_results,
        "result_count": len(unique_results),
        "search_params": params,
        "top_results_metadata": top_results_metadata,
    }


def deduplicate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate results based on section ID and code edition."""
    seen = set()
    unique = []

    for result in results:
        key = f"{result.get('code_edition')}:{result.get('division', '')}:{result.get('id')}"
        if key not in seen:
            seen.add(key)
            unique.append(result)

    return unique
