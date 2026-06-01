"""
Scoring engine for provision version search results.

Receives a pre-filtered queryset of in-force versions and scores them
against query terms using TF-IDF, synonym expansion, and fuzzy matching.
"""

from math import log
from typing import Any

from building_code_mcp.mcp_server import SYNONYMS
from django.db.models import QuerySet

from core.models import CodeEditionProvisionVersion

SEARCH_RESULT_LIMIT = 10


# Declared as Any so both the real module (try) and the None fallback
# (except) are assignable — the optional-import pattern without per-line
# ignores.  Call sites are guarded by FUZZY_AVAILABLE.
fuzz: Any
process: Any
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
    best_score = 0.0
    for target in target_terms:
        ratio = fuzz.ratio(query_term, target)
        if ratio > best_score:
            best_score = ratio
    if best_score >= threshold:
        return best_score / 100.0
    return 0.0


def _tf(term: str, counts: dict[str, int]) -> float:
    """Log-normalized term frequency."""
    raw = counts.get(term, 0)
    return (1 + log(raw)) if raw > 0 else 0.0


def compute_idf(versions_qs: QuerySet[CodeEditionProvisionVersion]) -> dict[str, float]:
    """Compute IDF weights from a queryset of provision versions."""
    total_docs = 0
    doc_freq: dict[str, int] = {}
    for kw_counts in versions_qs.values_list("keyword_counts", flat=True):
        if not kw_counts:
            continue
        total_docs += 1
        for keyword in kw_counts:
            doc_freq[keyword] = doc_freq.get(keyword, 0) + 1
    if total_docs == 0:
        return {}
    return {kw: log(1 + total_docs / df) for kw, df in doc_freq.items()}


def score_versions(
    query: str,
    versions_qs: QuerySet[CodeEditionProvisionVersion],
    idf_map: dict[str, float],
    provision_references: list[str] | None = None,
    limit: int = SEARCH_RESULT_LIMIT,
) -> list[dict[str, Any]]:
    """Score provision versions against a query using TF-IDF + fuzzy matching.

    Args:
        query: Space-joined keywords from the parsed user query.
        versions_qs: Pre-filtered queryset of in-force versions (with
            select_related and prefetch_related already applied).
        idf_map: Pre-computed IDF weights for the corpus.
        provision_references: Explicit provision ID references from the query.
        limit: Max results to return.

    Returns:
        Scored result dicts sorted by score descending.
    """
    limit = max(1, min(limit, 50))

    has_query = query and isinstance(query, str) and query.strip()
    has_refs = bool(provision_references)

    if not has_query and not has_refs:
        return []

    query_lower = query.lower().strip() if has_query else ""
    query_terms = set(query_lower.split()) if query_lower else set()
    expanded_terms = _expand_query_with_synonyms(query_terms) if query_terms else set()

    def get_idf(term: str) -> float:
        return idf_map.get(term, 1.0)

    # Filter the queryset to candidates matching keywords or references
    from django.db.models import Q

    criteria = Q()
    if query_lower:
        criteria |= Q(provision__provision_id__icontains=query_lower)
        for term in query_terms:
            criteria |= Q(title__icontains=term)
        if expanded_terms:
            for term in expanded_terms:
                criteria |= Q(keyword_counts__has_key=term)
    if has_refs:
        for ref in provision_references or []:
            criteria |= Q(provision__provision_id__icontains=ref)

    candidates = versions_qs.filter(criteria)

    results: list[dict[str, Any]] = []
    for version in candidates:
        provision = version.provision
        provision_id = provision.provision_id or ""
        title = version.title or ""
        kw_counts: dict[str, int] = version.keyword_counts or {}
        keywords = set(kw_counts.keys())
        title_words = set(title.lower().split())
        all_terms = keywords | title_words

        score = 0.0
        match_type = None

        # Provision reference match (highest priority)
        if has_refs:
            pid_lower = provision_id.lower()
            for ref in provision_references or []:
                if ref.lower() in pid_lower:
                    ref_score = 2.5 if pid_lower.endswith(ref.lower()) else 2.0
                    if ref_score > score:
                        score = ref_score
                        match_type = "provision_ref"

        # Exact query match in provision_id
        if score == 0 and query_lower and query_lower in provision_id.lower():
            score = 2.0 if provision_id.lower().endswith(query_lower) else 1.5
            match_type = "exact_id"
        elif score == 0 and expanded_terms:
            matches = expanded_terms & all_terms
            if matches:
                original_matches = query_terms & all_terms
                if original_matches:
                    score = sum(_tf(t, kw_counts) * get_idf(t) for t in original_matches) / sum(
                        get_idf(t) for t in query_terms
                    )
                    match_type = "exact"
                else:
                    score = (
                        sum(_tf(t, kw_counts) * get_idf(t) for t in matches)
                        / sum(get_idf(t) for t in expanded_terms)
                    ) * 0.9
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
            results.append({
                "version": version,
                "provision": provision,
                "id": provision_id,
                "title": title,
                "division": provision.division,
                "score": round(score, 3),
                "match_type": match_type,
                "code_edition": provision.edition.code_name,
                "html_content": version.html,
                "page_images": version.page_images,
                "tables": list(version.tables.all()),
                # Templates show "amended by O. Reg. X cl. Y" using a
                # single clause.  After the M2M migration the most
                # recent amending clause is the last contributing clause
                # in apply order; that's the one users want to see.
                "clause": version.last_contributing_clause,
                "is_base": version.version == 0,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
