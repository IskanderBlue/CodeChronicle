"""
Search execution logic combining applicability resolution and DB-backed maps.
"""

from typing import Any

from building_code_mcp.mcp_server import SYNONYMS
from django.db.models import Q

from core.models import CodeMapNode

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
