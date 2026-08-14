"""
Scoring engine for provision version search results.

Receives a pre-filtered queryset of in-force versions and scores them
against query terms using BM25-weighted keywords, synonym expansion, and
fuzzy matching.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from math import log
from typing import Any

from django.db.models import QuerySet

from config.search_limits import SEARCH_RESULT_CAP
from config.synonyms import SYNONYMS
from core.models import CodeEditionProvisionVersion

# Re-exported: the orchestrator and its tests read the render cap from here
# alongside SEARCH_CANDIDATE_LIMIT, but the constant itself lives outside this
# module — config has no Django imports, and this module imports core.models.
__all__ = ["SEARCH_CANDIDATE_LIMIT", "SEARCH_RESULT_CAP", "score_versions"]

#: Floor on the scored candidate pool handed to the grouping stage.  Grouping
#: can only pair results it can see, and pair members score identically (same
#: text), so they rank adjacent — a pool of just the display limit would drop
#: both members of any pair sitting below the cutoff and silently present a
#: transition as a single version.  The orchestrator raises this floor when the
#: display limit is large; scoring is already done by then, so the pool costs
#: nothing but the grouping stage's mapping lookups.
SEARCH_CANDIDATE_LIMIT = 50


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


# BM25 term-frequency parameters (standard Robertson/Walker values).  k1 caps
# how much repetition can help — the TF component saturates at k1 + 1, so the
# 269th occurrence of "fire" is worth barely more than the 5th.  b sets how
# strongly that saturation point scales with document length: index-like
# mega-provisions (Part 11 "Compliance Alternatives" tables mention every
# topic in the code) need proportionally more evidence than a focused article.
BM25_K1 = 1.2
BM25_B = 0.75

# Title-field parameters (BM25F).  A provision's title is scored as its own
# field, separately from the body, because the merged bag CCM ships cannot
# distinguish "this provision is *about* maintenance inspections" (the phrase
# is its title) from "it mentions them once in a proviso" — after tokenization
# both are the integer 1.  Ontario's drafting convention names each provision
# after its subject, which makes the title close to a hand-written topic label
# on every document in the corpus.
#
# This also relieves a real tension in ``BM25_B``.  b was set high (0.75)
# specifically to stop the Part 11 "Compliance Alternatives" mega-tables, which
# mention every topic in the code, from top-ranking every query — but b only
# knows "long documents are suspicious", so it penalizes a genuinely relevant
# long provision just as hard.  The title tells the two apart: the mega-table's
# title matches nothing, the relevant provision's title matches the query.
#
# ``b`` is low for titles: a title's length carries almost no spam signal, so
# normalizing it hard would mostly punish provisions with descriptive names.
BM25_B_TITLE = 0.3
#: How much one occurrence in the title outweighs one in the body.  The single
#: knob worth tuning here; 3.0 is the conventional starting point for corpora
#: with short, highly indicative titles.
BM25F_TITLE_WEIGHT = 3.0


def _bm25_saturate(tf: float) -> float:
    """Map an accumulated, length-normalized term frequency onto ``[0, k1+1)``.

    Split out from the field accumulation because BM25F saturates *once*, over
    the summed contributions of every field.  Saturating per field and adding
    the results would let a long body and a matching title each collect a
    nearly-full ``k1 + 1``, so a document could roughly double the intended
    ceiling by matching in two places.

    At a normalized frequency of 1.0 (one occurrence, average length, no title
    hit) this returns exactly 1.0 — the same anchor the scorer has always had,
    which is what keeps a perfect match on the typed words landing near 1.0
    after query-side normalization.
    """
    if tf <= 0:
        return 0.0
    return tf * (BM25_K1 + 1) / (BM25_K1 + tf)


def _bm25f_tf(
    term: str,
    counts: dict[str, int],
    title_counts: dict[str, int],
    body_norm: float,
    title_norm: float,
) -> float:
    """Field-weighted, then saturated, term frequency for one term.

    ``counts`` is CCM's ``keyword_counts`` — the title + body + table-text
    *union* — and ``title_counts`` its title-only companion, so the body's own
    count is the difference.  The subtraction is floored at zero: CCM truncates
    ``keyword_counts`` at its 1000 most frequent terms, so a rare title word on
    a mega-provision can be present in the title counts and absent from the
    union without either field being wrong.

    With an empty ``title_counts`` this reduces *exactly* to the single-field
    BM25 the scorer used before — ``raw * (k1+1) / (raw + k1*norm)`` is
    algebraically identical to ``saturate(raw/norm)``.  That equivalence is
    what makes an un-reloaded edition (no title counts yet) rank as it always
    did rather than ranking wrongly.
    """
    accumulated = 0.0

    raw_body = counts.get(term, 0) - title_counts.get(term, 0)
    if raw_body > 0:
        accumulated += raw_body / body_norm

    raw_title = title_counts.get(term, 0)
    if raw_title > 0:
        accumulated += BM25F_TITLE_WEIGHT * raw_title / title_norm

    return _bm25_saturate(accumulated)


def _field_length_norm(field_len: int, avg_len: float, b: float) -> float:
    """BM25 length normalizer ``1 - b + b * len/avg`` for one field.

    Never returns 0 for any ``b < 1`` (the ``1 - b`` term is a floor), so
    callers can divide by it unguarded even for a zero-length field.
    """
    if avg_len <= 0:
        return 1.0
    return 1 - b + b * (field_len / avg_len)


@dataclass(frozen=True)
class CorpusStats:
    """Corpus-level scoring inputs, computed in one pass over the count fields."""

    idf: dict[str, float] = field(default_factory=dict)
    #: Mean length of the *body* field — the union's token count minus the
    #: title's.  Not the whole document: title tokens are normalized against
    #: their own field average below.
    avg_body_len: float = 0.0
    #: Mean length of the title field, averaged over versions that *have* a
    #: title.  Untitled versions are excluded deliberately — a missing field is
    #: not a short field, and letting the many title-less versions drag the mean
    #: down would make ordinary titles look long and quietly shrink the title
    #: weight for exactly the provisions it is meant to help.
    avg_title_len: float = 0.0


def compute_corpus_stats(
    versions_qs: QuerySet[CodeEditionProvisionVersion],
) -> CorpusStats:
    """Compute IDF weights and per-field average lengths for a corpus.

    All of it comes from one pass over every version's count fields (the JSON
    columns are the expensive part to fetch, so one pass matters).

    IDF is computed over the union, not per field: a term is "in" a document
    whether it appeared in the title or the body.  Splitting IDF by field would
    make a title term's rarity depend on which field it landed in, which is not
    what rarity means.
    """
    total_docs = 0
    total_body_len = 0
    titled_docs = 0
    total_title_len = 0
    doc_freq: dict[str, int] = {}
    for kw_counts, title_counts in versions_qs.values_list(
        "keyword_counts", "title_keyword_counts",
    ):
        if not kw_counts:
            continue
        total_docs += 1
        title_len = sum((title_counts or {}).values())
        total_body_len += max(0, sum(kw_counts.values()) - title_len)
        if title_len:
            titled_docs += 1
            total_title_len += title_len
        for keyword in kw_counts:
            doc_freq[keyword] = doc_freq.get(keyword, 0) + 1
    if total_docs == 0:
        return CorpusStats()
    return CorpusStats(
        idf={kw: log(1 + total_docs / df) for kw, df in doc_freq.items()},
        avg_body_len=total_body_len / total_docs,
        avg_title_len=total_title_len / titled_docs if titled_docs else 0.0,
    )


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
    corpus_stats: CorpusStats,
    provision_references: list[str] | None = None,
    limit: int | None = SEARCH_RESULT_CAP,
    raw_query: str = "",
    direct_keywords: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Score provision versions against a query using BM25 + fuzzy matching.

    Args:
        query: Space-joined keywords from the parsed user query.
        versions_qs: Pre-filtered queryset of in-force versions (with
            select_related and prefetch_related already applied).
        corpus_stats: Pre-computed IDF weights and average document length
            for the corpus.
        provision_references: Explicit provision ID references from the query.
        limit: Max results to return, or ``None`` for every match.  This is
            never the display limit — the orchestrator splits by tier access,
            groups transition pairs, and only then trims to the user's cards.
            ``None`` is what the orchestrator passes: the loop below already
            builds a dict for every match before sorting, so truncating here
            saves no work and would hide (a) the true per-edition match counts
            the free-tier notice quotes and (b) the lower-ranked accessible
            results that fill a gated user's list.
        raw_query: The user's original typed text.  Used only to *derive* the
            direct terms when ``direct_keywords`` is absent: a keyword counts
            as direct if it appears verbatim here.  When both are empty, every
            keyword is treated as direct (back-compat for callers without
            either).
        direct_keywords: The words the reader actually typed, as
            ``config.query_keywords`` extracted them.  These score at full
            weight; everything else — the model's additions and the engine's
            synonyms — is *indirect* and carries the 0.9 weight.  Prefer this
            over the ``raw_query`` derivation, which cannot see through a
            hyphen: a typed ``spruce-pine-fir`` extracts as three terms, no one
            of which appears verbatim in the query, so the derivation files all
            three as the model's guesses.

    Returns:
        Scored result dicts sorted by score descending.
    """
    limit = None if limit is None else max(1, limit)

    has_query = query and isinstance(query, str) and query.strip()
    has_refs = bool(provision_references)

    if not has_query and not has_refs:
        return []

    query_lower = query.lower().strip() if has_query else ""
    query_terms = set(query_lower.split()) if query_lower else set()
    expanded_terms = _expand_query_with_synonyms(query_terms) if query_terms else set()

    # Direct terms = keywords the user literally typed.  The parser reads those
    # out of the query itself and the LLM then adds a keyword *family* ("defined
    # terms" -> defined / definition / definitions / terms); only the typed words
    # score at full weight, the rest join the synonyms in the 0.9-weighted
    # indirect pool.  Three sources, in falling order of authority: the parser's
    # own list, the verbatim derivation from the raw text, and — for a caller
    # with neither — every keyword treated as direct.
    if direct_keywords is not None:
        direct_terms = query_terms & {t.lower() for t in direct_keywords}
    else:
        raw_tokens = (
            set(re.findall(r"[a-z0-9][a-z0-9-]*", raw_query.lower()))
            if raw_query else set(query_terms)
        )
        direct_terms = query_terms & raw_tokens
    indirect_terms = expanded_terms - direct_terms

    def get_idf(term: str) -> float:
        return corpus_stats.idf.get(term, 1.0)

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
        # Title-only counts, same tokenizer, shipped alongside the union.  NULL
        # until the edition is reloaded from a CCM build that emits it; an
        # empty dict makes every title contribution zero, which is precisely
        # the single-field behaviour this scorer had before.
        title_counts: dict[str, int] = version.title_keyword_counts or {}
        # CCM tokenizes the title into keyword_counts at ingest, so the doc's
        # searchable terms are essentially its keys — a separate title-word set
        # would only re-add stopwords CCM deliberately filtered out, which can
        # match but never score.  The title keys are unioned in only to cover
        # CCM's 1000-term truncation of keyword_counts, which can drop a rare
        # title word from the union on a very long provision.
        all_terms = set(kw_counts.keys()) | set(title_counts.keys())

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
                # Per-field length factors: how far this document's body and
                # title sit above or below their own corpus averages.  Without
                # the body one the Part 11 "Compliance Alternatives"
                # mega-tables — which mention every term in the code at high
                # counts — top-rank every query.
                title_len = sum(title_counts.values())
                body_len = max(0, sum(kw_counts.values()) - title_len)
                body_norm = _field_length_norm(
                    body_len, corpus_stats.avg_body_len, BM25_B,
                )
                title_norm = _field_length_norm(
                    title_len, corpus_stats.avg_title_len, BM25_B_TITLE,
                )
                numerator = sum(
                    _bm25f_tf(t, kw_counts, title_counts, body_norm, title_norm)
                    * get_idf(t)
                    for t in direct_matched
                )
                # Indirect terms get the title weighting too.  They have to:
                # CCM's tokenizer does no stemming, so "inspections" in a title
                # is a different term from a typed "inspection" and reaches the
                # scorer only through the LLM's keyword family.  Boosting titles
                # for direct terms alone would make the title field fire or not
                # on the user's choice of plural.
                numerator += 0.9 * sum(
                    _bm25f_tf(t, kw_counts, title_counts, body_norm, title_norm)
                    * get_idf(t)
                    for t in indirect_matched
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
    return results if limit is None else results[:limit]
