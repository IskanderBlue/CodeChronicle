"""
Scoring engine for provision version search results.

Receives a pre-filtered queryset of in-force versions and scores them
against query terms using TF-IDF, synonym expansion, and fuzzy matching.
"""

import re
from collections.abc import Sequence
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


# Trailing clause suffix on a reference, e.g. "3.2.1(1)" / "(1-3)" / "(1,2)".
_REF_CLAUSE_RE = re.compile(r"\((?:\d+(?:[-,]\d+)*)\)$")


def _ref_parts(token: str) -> tuple[bool, tuple[str, ...]]:
    """Normalize a reference or ``table_id`` into ``(is_table, segments)``.

    Both user references (``table-3.1.4.7``, ``A-3.1.2``, ``9.10.14.``,
    ``3.2.1(1)``) and stored table ids (``Table-3.1.4.7.``) pass through here,
    so the two sides compare as the same dotted-segment tuple.  Splitting on
    ``.`` makes matching hierarchy-aware rather than substring-based: ``1.`` is
    a segment of ``("1", "2", "1")`` but emphatically not of ``("11", "2")``.
    """
    t = token.strip().lower()
    is_table = False
    table_marker = re.match(r"table[\s\-.]+", t)
    if table_marker:
        is_table, t = True, t[table_marker.end():]
    else:
        # Drop a leading division-letter prefix like "a-3.1.2".
        t = re.sub(r"^[a-z][\s\-]", "", t)
    t = _REF_CLAUSE_RE.sub("", t)
    return is_table, tuple(seg for seg in t.split(".") if seg)


def _match_reference(
    ref: str, provision_id: str, table_segments: Sequence[tuple[str, ...]],
) -> tuple[float, str] | None:
    """Best ``(score, match_type)`` for one reference against this provision.

    A single segment-aware check that replaces the old provision_ref/exact_id
    substring branches.  Exact and resolved-table matches rank highest (3.0);
    an ancestor reference (a true parent path) scores lower and decays with
    distance.  Returns ``None`` when the reference does not apply here.
    """
    is_table, segs = _ref_parts(ref)
    if not segs:
        return None

    if is_table:
        # Only a hit when the provision actually owns the referenced table.
        if any(segs == ts for ts in table_segments):
            return 3.0, "table_ref"
        return None

    pid = tuple(seg for seg in provision_id.strip().lower().split(".") if seg)
    if not pid:
        return None
    if segs == pid:
        return 3.0, "exact_id"
    # Ancestor: the reference is a true parent path of this provision id.
    if len(segs) < len(pid) and pid[: len(segs)] == segs:
        depth = len(pid) - len(segs)
        return max(1.0, 2.25 - 0.25 * depth), "ancestor_id"
    return None


def score_versions(
    query: str,
    versions_qs: QuerySet[CodeEditionProvisionVersion],
    idf_map: dict[str, float],
    provision_references: list[str] | None = None,
    limit: int = SEARCH_RESULT_LIMIT,
    raw_query: str = "",
) -> list[dict[str, Any]]:
    """Score provision versions against a query using TF-IDF + fuzzy matching.

    Args:
        query: Space-joined keywords from the parsed user query.
        versions_qs: Pre-filtered queryset of in-force versions (with
            select_related and prefetch_related already applied).
        idf_map: Pre-computed IDF weights for the corpus.
        provision_references: Explicit provision ID references from the query.
        limit: Max results to return.
        raw_query: The user's original typed text.  A keyword counts as a
            *direct* match only if it appears verbatim here; keywords the LLM
            added (morphological variants, related topics) and engine synonyms
            are *indirect* and carry the 0.9 weight.  When empty, every keyword
            is treated as direct (back-compat for callers without the raw text).

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

    # Direct terms = keywords the user literally typed.  The LLM parser expands
    # a query into a keyword *family* ("defined terms" -> defined / definition /
    # definitions / terms); only the typed words score at full weight, the rest
    # join the synonyms in the 0.9-weighted indirect pool.  Without a raw query
    # (older callers/tests) every keyword is treated as direct.
    raw_tokens = (
        set(re.findall(r"[a-z0-9][a-z0-9-]*", raw_query.lower()))
        if raw_query else set(query_terms)
    )
    direct_terms = query_terms & raw_tokens
    indirect_terms = expanded_terms - direct_terms

    def get_idf(term: str) -> float:
        return idf_map.get(term, 1.0)

    # Filter the queryset to candidates matching keywords or references
    from django.db.models import Q

    criteria = Q()
    if query_lower:
        # Keyword matching is via keyword_counts only.  CCM folds the title into
        # keyword_counts at ingest (it tokenizes the title alongside the body),
        # so has_key over the expanded terms already covers title words; a
        # separate title__icontains gate would only pull in candidates that then
        # score 0.  (A provision_id__icontains over the keyword text used to be
        # OR'd in here, but provision ids are dotted numbers — it never matched
        # alphabetic keywords and only added a dead ILIKE to every search.)
        for term in expanded_terms:
            criteria |= Q(keyword_counts__has_key=term)
    if has_refs:
        for ref in provision_references or []:
            is_table, segs = _ref_parts(ref)
            if not segs:
                continue
            # Coarse superset filter on the dotted core; the segment-aware
            # matcher below decides the precise hits.  Table references look at
            # the provision's tables, plain references at its id.
            core = ".".join(segs)
            if is_table:
                criteria |= Q(tables__table_id__icontains=core)
            else:
                criteria |= Q(provision__provision_id__icontains=core)

    # No usable filter — e.g. a refs-only query whose references were all
    # unparseable (every `_ref_parts` returned no segments). An empty Q matches
    # the entire corpus, so bail here rather than scan and score every in-force
    # version only to discard them all.
    if not criteria:
        return []

    # distinct(): the tables__ join fans out to-many rows; without it a
    # provision with several tables would be scored more than once.
    candidates = versions_qs.filter(criteria).distinct()

    results: list[dict[str, Any]] = []
    for version in candidates:
        provision = version.provision
        provision_id = provision.provision_id or ""
        version_tables = list(version.tables.all())
        title = version.title or ""
        kw_counts: dict[str, int] = version.keyword_counts or {}
        # CCM tokenizes the title into keyword_counts at ingest, so the doc's
        # searchable terms are exactly its keys — a separate title-word set
        # would only re-add stopwords CCM deliberately filtered out, which can
        # match but never score (tf reads keyword_counts).
        all_terms = set(kw_counts.keys())

        score = 0.0
        match_type = None
        # The specific terms (or reference) that earned the score, surfaced to
        # the UI so the results card can explain *why* this provision matched.
        matched_terms: list[str] = []

        # --- Unified reference / table match (segment-aware) ---
        # One check replaces the old provision_ref + exact_id substring
        # branches.  Ids compare as dotted-segment tuples, so "1." never
        # matches "11.2.1", and a "Table-..." reference resolves against the
        # provision's own tables rather than its number.  Parser-extracted
        # references already cover bare ids typed as keywords, so the old
        # query-text-in-id fallback is folded in here.
        table_segs = [_ref_parts(t.table_id)[1] for t in version_tables]
        for ref in provision_references or []:
            hit = _match_reference(ref, provision_id, table_segs)
            if hit and hit[0] > score:
                score, match_type = hit
                matched_terms = [ref]

        matched_indirect: list[str] = []
        if score == 0 and expanded_terms:
            # Blend direct (typed) and indirect (LLM-added + synonym) hits in one
            # pass: indirect contributions carry the 0.9 weight, and the score is
            # normalized by the *intended* query (direct terms when the user
            # typed any, else the indirect set).  This keeps a full match on the
            # typed words from being diluted by the LLM's extra variants.
            direct_matched = direct_terms & all_terms
            indirect_matched = indirect_terms & all_terms
            if direct_matched or indirect_matched:
                numerator = sum(_tf(t, kw_counts) * get_idf(t) for t in direct_matched)
                numerator += 0.9 * sum(
                    _tf(t, kw_counts) * get_idf(t) for t in indirect_matched
                )
                norm_terms = direct_terms if direct_matched else indirect_terms
                denom = sum(get_idf(t) for t in norm_terms)
                score = numerator / denom if denom else 0.0
                match_type = "exact" if direct_matched else "synonym"
                matched_terms = sorted(direct_matched)
                matched_indirect = sorted(indirect_matched)

        if score == 0 and FUZZY_AVAILABLE:
            # Fuzzy-match over the expanded set (synonyms included) and
            # normalize by its size, mirroring the synonym branch's basis.
            # This keeps the two lower tiers on the same footing so a synonym
            # that only fuzzily matches isn't penalized harder than a typo of
            # an original term would be.
            fuzzy_scores = []
            fuzzy_terms = []
            for term in expanded_terms:
                fscore = _fuzzy_match_score(term, all_terms)
                if fscore > 0:
                    fuzzy_scores.append(fscore)
                    fuzzy_terms.append(term)
            if fuzzy_scores:
                score = (sum(fuzzy_scores) / len(expanded_terms)) * 0.8
                match_type = "fuzzy"
                matched_terms = sorted(fuzzy_terms)

        if score > 0:
            results.append({
                "version": version,
                "provision": provision,
                "id": provision_id,
                "title": title,
                "division": provision.division,
                "score": round(score, 3),
                "match_type": match_type,
                "matched_terms": matched_terms,
                "matched_terms_indirect": matched_indirect,
                "code_edition": provision.edition.code_name,
                "html_content": version.html,
                "page_images": version.page_images,
                "tables": version_tables,
                # Templates show "amended by O. Reg. X cl. Y" using a
                # single clause.  After the M2M migration the most
                # recent amending clause is the last contributing clause
                # in apply order; that's the one users want to see.
                "clause": version.last_contributing_clause,
                "is_base": version.version == 0,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
