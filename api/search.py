"""
Search execution logic combining applicability resolution and DB-backed maps.
"""

from datetime import date
from typing import Any, Dict, List

from building_code_mcp.mcp_server import SYNONYMS
from coloured_logger import Logger
from django.db.models import Q

from config.code_metadata import get_applicable_codes, get_map_codes
from core.models import CodeMapNode

logger = Logger(__name__)


SEARCH_RESULT_LIMIT = 10  # Unified limit for search results


try:
    from rapidfuzz import fuzz, process

    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False
    fuzz = None
    process = None


def _expand_query_with_synonyms(query_terms: set[str]) -> set[str]:
    expanded = set(query_terms)
    for term in query_terms:
        if term in SYNONYMS:
            expanded.update(SYNONYMS[term])
    return expanded


def _fuzzy_match_score(query_term: str, target_terms: set[str], threshold: int = 80) -> float:
    if not FUZZY_AVAILABLE or not target_terms:
        return 0.0
    best_score = 0
    for target in target_terms:
        ratio = fuzz.ratio(query_term, target)
        if ratio > best_score:
            best_score = ratio
    if best_score >= threshold:
        return best_score / 100.0
    return 0.0


def _suggest_similar_keywords(query: str, map_code: str | None = None, limit: int = 3) -> list[str]:
    if not FUZZY_AVAILABLE or not query:
        return []

    keyword_qs = CodeMapNode.objects.all()
    if map_code:
        keyword_qs = keyword_qs.filter(code_map__map_code=map_code)

    keywords: set[str] = set()
    for row in keyword_qs.values_list("keywords", flat=True):
        if not row:
            continue
        for kw in row:
            if isinstance(kw, str):
                keywords.add(kw.lower())

    if not keywords:
        return []

    matches = process.extract(query.lower(), list(keywords), limit=limit, score_cutoff=60)
    return [match[0] for match in matches]


def _search_code_db(
    query: str,
    map_code: str,
    limit: int,
    section_references: list[str] | None = None,
) -> dict[str, Any]:
    limit = max(1, min(limit, 50))

    has_query = query and isinstance(query, str) and query.strip()
    has_sections = bool(section_references)

    if not has_query and not has_sections:
        return {"error": "Query is required", "query": "", "results": [], "total": 0}

    query_lower = query.lower().strip() if has_query else ""
    query_terms = set(query_lower.split()) if query_lower else set()
    expanded_terms = _expand_query_with_synonyms(query_terms) if query_terms else set()

    criteria = Q()

    if query_lower:
        criteria |= Q(node_id__icontains=query_lower)
        for term in query_terms:
            criteria |= Q(title__icontains=term)
        if expanded_terms:
            criteria |= Q(keywords__overlap=list(expanded_terms))

    if has_sections:
        for ref in section_references:
            criteria |= Q(node_id__icontains=ref)

    candidates = (
        CodeMapNode.objects.filter(code_map__map_code=map_code)
        .filter(criteria)
        .only("node_id", "title", "page", "page_end", "keywords")
    )

    results: list[dict[str, Any]] = []
    for node in candidates:
        section_id = node.node_id or ""
        title = node.title or ""
        keywords = set(kw.lower() for kw in (node.keywords or []))
        title_words = set(title.lower().split())
        all_terms = keywords | title_words

        score = 0.0
        match_type = None

        if has_sections:
            sid_lower = section_id.lower()
            for ref in section_references:
                if ref.lower() in sid_lower:
                    ref_score = 2.5 if sid_lower.endswith(ref.lower()) else 2.0
                    if ref_score > score:
                        score = ref_score
                        match_type = "section_ref"

        if score == 0 and query_lower and query_lower in section_id.lower():
            score = 2.0 if section_id.lower().endswith(query_lower) else 1.5
            match_type = "exact_id"
        elif score == 0 and expanded_terms:
            matches = expanded_terms & all_terms
            if matches:
                original_matches = query_terms & all_terms
                if original_matches:
                    score = len(original_matches) / len(query_terms)
                    match_type = "exact"
                else:
                    score = (len(matches) / len(expanded_terms)) * 0.9
                    match_type = "synonym"

        if score == 0 and FUZZY_AVAILABLE:
            fuzzy_scores = []
            for term in query_terms:
                fscore = _fuzzy_match_score(term, all_terms)
                if fscore > 0:
                    fuzzy_scores.append(fscore)
            if fuzzy_scores:
                score = (sum(fuzzy_scores) / len(query_terms)) * 0.8
                match_type = "fuzzy"

        if score > 0:
            result_item = {
                "id": section_id,
                "title": title,
                "page": node.page,
                "page_end": node.page_end,
                "score": round(score, 3),
            }
            if match_type:
                result_item["match_type"] = match_type
            results.append(result_item)

    results.sort(key=lambda x: x["score"], reverse=True)
    limited_results = results[:limit]

    response = {"results": limited_results, "total": len(results)}
    if len(results) == 0:
        similar = _suggest_similar_keywords(query, map_code)
        if similar:
            response["suggestion"] = (
                f"No results for '{query}'. Did you mean: {', '.join(similar)}?"
            )
        else:
            response["suggestion"] = (
                f"No results for '{query}'. Try different keywords or check spelling."
            )
    return response


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
