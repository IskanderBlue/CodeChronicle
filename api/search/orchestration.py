"""
Search orchestration: execute_search and result deduplication.
"""

from datetime import date
from typing import Any, Dict, List

from coloured_logger import Logger

from config.code_metadata import get_applicable_codes, get_map_codes
from core.models import CodeMapNode

from .engine import SEARCH_RESULT_LIMIT, _search_code_db

logger = Logger(__name__)


def execute_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute search based on parsed parameters.
    """
    search_date_str = params.get("date")
    keywords = params.get("keywords", [])
    province = params.get("province", "ON")
    section_references = params.get("section_references", [])

    try:
        search_date = date.fromisoformat(search_date_str)
    except (ValueError, TypeError):
        search_date = date.today()

    # Step 1: Resolve applicable codes
    applicable_codes = get_applicable_codes(province, search_date)

    if not applicable_codes:
        return {"error": f"No building codes found for {province} on {search_date}", "results": []}

    all_results = []

    # Step 2: Search each code using DB-backed map identifiers
    for code_name in applicable_codes:
        map_codes = get_map_codes(code_name)
        if not map_codes:
            logger.warning("No map codes configured for %s, skipping", code_name)
            continue

        for map_code in map_codes:
            try:
                search_response = _search_code_db(
                    query=" ".join(keywords),
                    map_code=map_code,
                    limit=SEARCH_RESULT_LIMIT,
                    section_references=section_references or None,
                )

                results = search_response.get("results", [])

                # Build lookups from DB (search_code doesn't return these)
                bbox_lookup: Dict[str, Any] = {}
                html_lookup: Dict[str, str] = {}
                notes_html_lookup: Dict[str, str] = {}
                result_ids = [r.get("id") for r in results if r.get("id")]
                if result_ids:
                    nodes = CodeMapNode.objects.filter(
                        code_map__map_code=map_code,
                        node_id__in=result_ids,
                    ).values("node_id", "bbox", "html", "notes_html")
                    for node in nodes:
                        node_id = node["node_id"]
                        if node.get("bbox"):
                            bbox_lookup[node_id] = node["bbox"]
                        if node.get("html"):
                            html_lookup[node_id] = node["html"]
                        if node.get("notes_html"):
                            notes_html_lookup[node_id] = node["notes_html"]

                # Tag each result with edition info and the specific map it came from
                for result in results:
                    result["code_edition"] = code_name
                    result["map_code"] = map_code
                    result["source_date"] = search_date.isoformat()
                    result["bbox"] = bbox_lookup.get(result.get("id"))
                    result["html_content"] = html_lookup.get(result.get("id"))
                    result["notes_html"] = notes_html_lookup.get(result.get("id"))

                all_results.extend(results)
            except Exception as e:
                logger.error("Error searching %s (map=%s): %s", code_name, map_code, e)

    # Step 3: Deduplicate and format
    unique_results = deduplicate_results(all_results)

    # Extract minimal metadata for history (top N)
    top_results_metadata = []
    for r in unique_results[:SEARCH_RESULT_LIMIT]:
        top_results_metadata.append(
            {
                "code": r.get("code_edition", "Unknown"),
                # Extract year from code string if possible, or source date
                "year": r.get("source_date", "")[:4],
                "section_id": r.get("id", ""),
                "title": r.get("title", "Untitled Section"),
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
    """
    Deduplicate results based on section ID and code edition.
    """
    seen = set()
    unique = []

    for r in results:
        key = f"{r.get('code_edition')}:{r.get('id')}"
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique
