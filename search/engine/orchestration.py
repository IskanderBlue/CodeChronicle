"""
Search orchestration: query provision versions in force, score, group transitions.
"""

from collections import defaultdict
from datetime import date
from typing import Any

from django.db import models
from django.db.models import Prefetch, Q

from core.models import (
    CodeEditionProvisionVersion,
    CodeEditionProvisionVersionClause,
    ProvinceCode,
    ProvisionMapping,
    RegulationClause,
)
from data.part_applicability import (
    PART_BOOST,
    PART_DEMOTE,
    Verdict,
    part_of,
    source_for,
    verdict_for,
)
from data.search_limits import (
    CLOSE_MATCH_THRESHOLD,
    SCORE_BUCKET_WIDTH,
    score_buckets,
)
from search.engine.engine import (
    SEARCH_CANDIDATE_LIMIT,
    SEARCH_RESULT_CAP,
    compute_corpus_stats,
    score_versions,
)


def _clause_through_prefetch() -> Prefetch:
    """Prefetch the apply_order-ordered clause through set, warmed with
    ``clause__regulation``.

    Lets ``CodeEditionProvisionVersion.first_contributing_clause`` /
    ``last_contributing_clause`` read from the prefetch cache instead of firing
    a query per version (an N+1 across the amendment chain and the per-result
    "Next amendment" copy line).  Returns a fresh object per call so it can be
    attached at several depths without sharing prefetch state.
    """
    return Prefetch(
        "codeeditionprovisionversionclause_set",
        queryset=CodeEditionProvisionVersionClause.objects.select_related(
            "clause__regulation"
        ),
    )


#: How many locked titles the "more results on Pro" section lists before it
#: falls back to a bare count.  A gated query can strand hundreds of matches;
#: the point is to prove the content exists, not to ship the whole index.
LOCKED_PREVIEW_LIMIT = 25


def execute_search(
    params: dict[str, Any],
    *,
    allowed_editions: frozenset[str] | None = None,
    match_threshold: float = CLOSE_MATCH_THRESHOLD,
    result_cap: int = SEARCH_RESULT_CAP,
) -> dict[str, Any]:
    """Main search entry point.

    Queries all provision versions in force for a province at a date,
    scores them against parsed keywords, splits by tier access, and groups
    transitions.

    Args:
        params: Parsed query params (date, province, keywords, references).
        allowed_editions: ``CodeEdition.code_name`` values this searcher may
            open, or ``None`` for unrestricted.  Resolved by ``accounts.access``
            and passed in so this layer stays tier-agnostic.
        match_threshold: Relevance floor for a *close* match.  Everything
            reported — the shown results, the counts, the locked teaser — is
            measured above this line, so the numbers on screen agree.  ``0.0``
            reports every scored match.
        result_cap: Hard ceiling on rendered cards.  Applied last, to the
            *accessible* results, and only ever a backstop against a 400-match
            query rendering 400 cards — the floor is what decides relevance.
            ``result_count < accessible_match_count`` is how a caller knows it
            bound and that the UI owes the reader an explanation.
    """
    search_date = date.fromisoformat(params["date"])
    province = params.get("province", "ON")
    keywords = params.get("keywords", [])
    provision_references = params.get("section_references", [])

    has_query = bool(keywords) or bool(provision_references)
    if not has_query:
        return {
            "applicable_codes": [],
            "results": [],
            "result_count": 0,
            "search_params": params,
            "top_results_metadata": [],
            "locked_editions": {},
            "locked_preview": [],
            "accessible_match_count": 0,
            "match_threshold": match_threshold,
            "weak_matches_only": False,
            "score_buckets": [],
            "score_bucket_width": SCORE_BUCKET_WIDTH,
            "close_match_count": 0,
            "cap_binds": False,
        }

    # All provision versions in force for this province at search_date
    code_ids = ProvinceCode.objects.filter(
        province=province
    ).values_list("code_id", flat=True)

    # Contract: filter out zero-width "as-filed but superseded same day"
    # emissions (``ineffective_date == effective_date``) — legal in the
    # JSON, never actually in force.
    in_force_qs = CodeEditionProvisionVersion.objects.filter(
        provision__edition__code_id__in=code_ids,
        effective_date__lte=search_date,
    ).filter(
        Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=search_date)
    ).exclude(
        ineffective_date=models.F("effective_date")
    ).select_related(
        "provision__edition__code",
        "provision__parent",
        "transition_provision__provision",
    ).prefetch_related(
        "tables",
        # Within-edition citations + the provision each points at, so the
        # formatter can link them inline without a query per result.  The
        # alternate (curator's intended reading) rides along so the printed
        # link can carry its corrected-reading chip without another query.
        "cross_references__to_provision",
        "cross_references__alternates__to_provision",
        "contributing_clauses__regulation",
        # Through-set (apply_order ordered) so the result version's
        # last_contributing_clause reads from cache rather than re-querying.
        _clause_through_prefetch(),
        # Full chain for the amendment-chain rail; each entry's
        # last_contributing_clause needs the through set too.
        Prefetch(
            "provision__versions",
            queryset=CodeEditionProvisionVersion.objects
                .prefetch_related(
                    "contributing_clauses__regulation",
                    _clause_through_prefetch(),
                )
                .order_by("version"),
        ),
        # Next-version-not-in-force lookup for the "Next amendment" line; its
        # first_contributing_clause names the upcoming regulation, so warm the
        # through set here too (else one query per result).
        Prefetch(
            "provision__versions",
            queryset=CodeEditionProvisionVersion.objects
                .filter(effective_date__gt=search_date)
                .prefetch_related(_clause_through_prefetch())
                .order_by("effective_date")[:1],
            to_attr="next_versions",
        ),
        "provision__appendix_entries__versions",
        "provision__edition__regulations",
    )

    corpus_stats = compute_corpus_stats(in_force_qs)

    # Score every match, split by access, group, *then* trim to the display
    # limit.  Every step of that order is load-bearing:
    #
    #  * Scoring is unlimited because the loop builds a dict per match before
    #    sorting anyway — a slice here would save nothing and would cost us the
    #    exact per-edition counts the free-tier notice quotes.
    #  * The access split runs before the trim so a gated searcher's cards are
    #    filled from what they can actually read.  Trimming first (the old
    #    order) let a locked edition with more in-force provisions monopolise
    #    every slot and hand the gate an all-locked list, so the UI reported
    #    "nothing matched" about a corpus that had matched.
    #  * Grouping runs before the trim because it can only pair results it can
    #    see; trimming first would drop both members of a pair below the cutoff
    #    and render a transition as a lone version.
    scored = score_versions(
        query=" ".join(keywords),
        versions_qs=in_force_qs,
        corpus_stats=corpus_stats,
        provision_references=provision_references,
        limit=None,
        raw_query=params.get("raw_query", ""),
        direct_keywords=params.get("direct_keywords"),
    )

    scored = _apply_part_boost(scored, params, search_date)

    accessible_all, locked_all = _split_by_access(scored, allowed_editions)

    # Relevance floor. Applied per side and *after* the access split so the two
    # counts on screen are computed the same way — a floored locked count under
    # an unfloored header count would be two answers to one question.
    accessible = [r for r in accessible_all if r["score"] >= match_threshold]
    locked = [r for r in locked_all if r["score"] >= match_threshold]

    # How many actually cleared the line, captured before the fallback can
    # replace the list. The threshold control reports this: if it reported the
    # fallback's size it would claim hundreds of matches were kept while
    # drawing every bar below the line as dropped.
    close_match_count = len(accessible)

    # Fallback: a floor that empties the list would recreate the exact failure
    # the access split just fixed — "nothing matched" over a corpus that had.
    # Show the weak matches instead and let the caller say so.
    weak_matches_only = bool(accessible_all) and not accessible
    if weak_matches_only:
        accessible = accessible_all

    # Grouping is the expensive stage (mapping lookups over the set), so it
    # sees a pool rather than the whole accessible list — deep enough that a
    # transition pair straddling the display cutoff still reunites.
    pool = max(SEARCH_CANDIDATE_LIMIT, result_cap * 2)
    grouped = _group_transitions(accessible[:pool])
    results = _limit_with_pairs(grouped, result_cap)

    # Whether the cap actually held anything back, decided where the trimming
    # happens rather than by comparing the rendered rows against the match
    # count.  Those two differ for reasons that have nothing to do with the cap
    # — grouping keeps two sides of a transition and drops any third in-force
    # version — and a header that reads "77 OF 78" invites the reader to hunt
    # for a result nothing withheld.
    cap_binds = len(results) < len(grouped)

    results = _add_source_date(results, search_date)

    applicable_codes = _unique_edition_names(results)

    return {
        "applicable_codes": applicable_codes,
        "results": results,
        "result_count": len(results),
        "search_params": params,
        "top_results_metadata": [
            {
                "code": r.get("code_edition"),
                "year": r.get("source_date", "")[:4],
                "section_id": r.get("id"),
                "title": r.get("title", ""),
            }
            for r in results
        ],
        # Exact counts, not pool-bounded: every match was scored, so the
        # teaser can name a real number instead of implying the pool size was
        # the whole story.
        "locked_editions": _match_counts(locked),
        "locked_preview": identity_preview(locked),
        # Accessible matches that exist beyond the display limit — what the
        # results-per-search control can still reveal.
        "accessible_match_count": len(accessible),
        "match_threshold": match_threshold,
        # True when nothing cleared the floor and the weak matches are being
        # shown anyway; the UI says so rather than passing them off as close.
        "weak_matches_only": weak_matches_only,
        # The distribution the threshold control is drawn over: counts per
        # score band across everything this searcher could see, floor ignored.
        # Measured on the accessible side only — every number on the page is
        # about the list they can read, and the locked side has its own count.
        "score_buckets": score_buckets([r["score"] for r in accessible_all]),
        "score_bucket_width": SCORE_BUCKET_WIDTH,
        "close_match_count": close_match_count,
        # True only when result_cap trimmed rows — the one case where the UI
        # owes the reader an explanation for a shorter list than the count.
        "cap_binds": cap_binds,
    }


def _apply_part_boost(
    results: list[dict[str, Any]],
    params: dict[str, Any],
    search_date: date,
) -> list[dict[str, Any]]:
    """Rank the part that governs the reader's building above the one that does not.

    **Here rather than in the scorer, on purpose.**  ``score_versions`` answers
    "how well do these words match this text".  This answers "does this part
    apply to this building".  Two different questions, and folding the second
    into the BM25F loop would make ``BM25F_TITLE_WEIGHT`` untunable — a title
    weight and a part weight would only ever be observable as their product.

    **Before the access split**, so everything downstream is measured on the
    ranking the reader actually sees: the relevance floor, the score
    distribution the floor control is drawn over, and both sides' counts.  A
    floor applied to unboosted scores and a page ordered by boosted ones would
    be two answers to one question.

    A multiplier, never a filter: this function removes nothing, because a
    house is routinely governed by a Part 3 provision through a cross-reference
    and an answer that is merely lower down can still be read.

    **That is not a promise that the page is unchanged.**  The relevance floor
    runs after this, on the scores this leaves behind, so a demoted result can
    fall under the reader's line and go.  The alternative — flooring the
    unboosted scores — would order the page by one measure and count it by
    another, which the whole tier-split design exists to prevent.  So the
    ordering stays and the copy says so; no surface may claim the results are
    untouched.

    Every result carries its verdict out, including ``unknown``, so the UI can
    say why a result moved instead of silently reordering the page.
    """
    occupancy = params.get("occupancy")
    if not occupancy:
        # No building in the question: nothing to prefer, and no verdict to
        # report.  The common case, and it must cost nothing.
        return results

    storeys = params.get("storeys")
    area_m2 = params.get("area_m2")

    for result in results:
        # provision__edition is select_related on the in-force queryset, so
        # this reads from memory rather than firing a query per result.
        verdict = verdict_for(
            edition_id=result["provision"].edition.edition_id,
            division=result["division"],
            provision_id=result["id"],
            occupancy=occupancy,
            storeys=storeys,
            area_m2=area_m2,
            on_date=search_date,
        )
        result["part_verdict"] = verdict.value
        if verdict is Verdict.UNKNOWN:
            continue
        # The facts a reader needs to check the move: how far it moved, which
        # part decided it, and the article that says so.  The sentence itself
        # is the formatter's job, like every other "why this result" line.
        factor = 1 + PART_BOOST if verdict is Verdict.APPLIES else 1 - PART_DEMOTE
        result["score"] = round(result["score"] * factor, 3)
        result["part_factor"] = round(factor, 2)
        result["part_number"] = part_of(result["id"])
        result["part_source"] = source_for(
            edition_id=result["provision"].edition.edition_id,
            provision_id=result["id"],
            on_date=search_date,
        )

    # The engine sorted by score and the scores have just changed.  Sorted
    # unconditionally: Timsort is linear on an already-ordered list, so a flag
    # to skip it would be parallel state bought for nothing.
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def _split_by_access(
    results: list[dict[str, Any]], allowed_editions: frozenset[str] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition scored results into (accessible, locked), relevance order kept.

    ``allowed_editions is None`` means unrestricted — the common Pro path, and
    the one that must not pay for the split.
    """
    if allowed_editions is None:
        return results, []
    accessible: list[dict[str, Any]] = []
    locked: list[dict[str, Any]] = []
    for result in results:
        target = (
            accessible
            if result.get("code_edition", "") in allowed_editions
            else locked
        )
        target.append(result)
    return accessible, locked


def _match_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    """``{edition code_name: match count}`` over a scored result list."""
    counts: dict[str, int] = {}
    for result in results:
        name = result.get("code_edition", "")
        counts[name] = counts.get(name, 0) + 1
    return counts


def identity_preview(
    results: list[dict[str, Any]], limit: int = LOCKED_PREVIEW_LIMIT
) -> list[dict[str, Any]]:
    """Identity-only rows: provision id, division, title, edition.

    The same fields the locked lineage rows and edition-nav teasers show, and
    deliberately no body text — the point is to prove the match exists and is
    relevant, not to serve the content.

    Two callers now.  The free-tier teaser passes the *locked* results (the
    reader's plan does not cover them); the rate-limit teaser passes the
    *accessible* results (the reader's plan covers them, but they have spent
    the day's allowance).  One function because the two lists must look
    identical on screen: they are the same promise, made for different
    reasons, and a reader who learns to read one has learned to read both.
    """
    return [
        {
            "id": result.get("id", ""),
            "division": result.get("division", ""),
            "title": result.get("title", ""),
            "code_edition": result.get("code_edition", ""),
        }
        for result in results[:limit]
    ]


def deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate provision results, keeping the highest-scoring."""
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for result in results:
        key = (
            result.get("id", ""),
            result.get("division", ""),
            result.get("code_edition", ""),
        )
        existing = seen.get(key)
        if existing is None or result.get("score", 0) > existing.get("score", 0):
            seen[key] = result
    return list(seen.values())


def _group_transitions(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group results where a provision has 2+ in-force versions (transition).

    During a transition period, the same provision has overlapping
    effective_date/ineffective_date ranges, so both versions appear in
    results. Group them so the formatter can build a transition compare view.
    """
    # Key on the edition too: this branch is for one provision's overlapping
    # versions, and version numbers only order within an edition. A same-id
    # provision in two editions (e.g. OBC 2006 C 1.10.2.4. ↔ 2012 C 1.10.2.4.,
    # both v0 during the inspection transition) must instead fall through to
    # the ProvisionMapping branch, where the mapping row says which side is
    # old and which is new — version numbers tie across editions and would
    # leave old/new to input order.
    by_provision: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        key = (
            result.get("id", ""),
            result.get("division", ""),
            result.get("code_edition", ""),
        )
        by_provision[key].append(result)

    output: list[dict[str, Any]] = []
    for key, group in by_provision.items():
        if len(group) == 1:
            output.append(group[0])
            continue

        # Multiple versions = transition. Sort by version number descending.
        group.sort(key=lambda r: _version_num(r), reverse=True)
        newer = group[0]
        older = group[1]

        # Build transition context from the newer version's transition_provision FK
        transition_text = ""
        newer_version = newer.get("version")
        if newer_version and newer_version.transition_provision:
            transition_text = newer_version.transition_provision.html

        # Both members share a pair_key (the provision identity that
        # ``by_provision`` grouped on) so the formatter can re-unite them;
        # is_primary marks the newer version as the "new" side.
        pair_key = f"overlap:{key[0]}:{key[1]}:{key[2]}"
        newer["transition_context"] = {
            "pair_key": pair_key,
            "is_primary": True,
            "transition_text": transition_text,
        }
        older["transition_context"] = {
            "pair_key": pair_key,
            "is_primary": False,
            "transition_text": transition_text,
        }
        output.append(newer)
        output.append(older)

    # Cross- and intra-edition transitions via ProvisionMapping
    output = _merge_provision_mapping_transitions(output)

    return output


def _merge_provision_mapping_transitions(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Check for old↔new provision pairs via ProvisionMapping.

    If provision A maps to provision B, and both appear in results
    (without an existing transition_context), group them as a transition
    pair.  The pair may straddle editions (cross-edition mapping) or sit
    inside a single edition (intra-edition renumber); we surface both
    through the same transition_context, with ``same_edition`` letting
    the UI render them distinctly.

    For intra-edition pairs the transition prose comes from the gazette
    clause that triggered the renumber — found among the
    ``introduced_by_version``'s ``contributing_clauses`` as the one
    whose action is ``renumber``.  For cross-edition pairs no such
    clause exists; we fall back to the new version's
    ``transition_provision`` (a Division C / Part 12 entry on the
    receiving edition).
    """
    # Build lookup: provision PK -> result (only ungrouped results)
    ungrouped = [r for r in results if not r.get("transition_context")]
    if not ungrouped:
        return results

    provision_pks = [
        r["provision"].pk for r in ungrouped if r.get("provision")
    ]
    if not provision_pks:
        return results

    mappings = ProvisionMapping.objects.filter(
        Q(old_provision_id__in=provision_pks) | Q(new_provision_id__in=provision_pks)
    ).select_related(
        "old_provision__edition",
        "new_provision__edition",
        "introduced_by_version",
    ).prefetch_related(
        "introduced_by_version__contributing_clauses__regulation",
    )

    if not mappings:
        return results

    by_pk: dict[int, dict[str, Any]] = {}
    for r in ungrouped:
        prov = r.get("provision")
        if prov:
            by_pk[prov.pk] = r

    paired_pks: set[int] = set()
    for mapping in mappings:
        old_pk = mapping.old_provision_id
        new_pk = mapping.new_provision_id
        old_result = by_pk.get(old_pk)
        new_result = by_pk.get(new_pk)
        if not old_result or not new_result:
            continue
        if old_pk in paired_pks or new_pk in paired_pks:
            continue

        same_edition = (
            mapping.old_provision.edition_id == mapping.new_provision.edition_id
        )

        transition_text = ""
        if same_edition and mapping.introduced_by_version is not None:
            # The contract pins introduced_by to the new-id version whose
            # contributing clauses include the renumber gazette directive.
            # Find that clause among the version's contributing clauses.
            renumber_clause = (
                mapping.introduced_by_version.contributing_clauses
                .filter(action=RegulationClause.Action.RENUMBER)
                .first()
            )
            if renumber_clause is not None:
                transition_text = renumber_clause.clause_text
        else:
            new_version = new_result.get("version")
            if new_version and hasattr(new_version, "transition_provision"):
                tp = new_version.transition_provision
                if tp:
                    transition_text = tp.html

        # The mapping row uniquely identifies the pair; both members share it
        # so the formatter re-unites them even across a renumber (different
        # provision ids) or within one edition (same_edition).
        pair_key = f"map:{mapping.pk}"
        new_result["transition_context"] = {
            "pair_key": pair_key,
            "is_primary": True,
            "transition_text": transition_text,
            "same_edition": same_edition,
            "mapping_type": mapping.mapping_type,
        }
        old_result["transition_context"] = {
            "pair_key": pair_key,
            "is_primary": False,
            "transition_text": transition_text,
            "same_edition": same_edition,
            "mapping_type": mapping.mapping_type,
        }
        paired_pks.add(old_pk)
        paired_pks.add(new_pk)

    return results


def _limit_with_pairs(
    results: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Trim to ``limit`` cards, counting a transition pair as a single card.

    Both members of a pair render as one compare card, so charging them two
    slots would let a transition crowd out an unrelated result.  A member whose
    partner is already admitted rides in free — and the scan continues past the
    slot cap looking for exactly those partners, since nothing guarantees the
    two sit adjacent in score order.

    Admitting a pair by its higher-scoring member (the one that reaches the cap
    first) is what keeps this stable: the lower-scoring member is never the
    reason a pair is admitted, so the cutoff behaves the same as it would for a
    single result at that rank.
    """
    kept: list[dict[str, Any]] = []
    admitted_pairs: set[str] = set()
    cards = 0

    for result in results:
        pair_key = (result.get("transition_context") or {}).get("pair_key")
        if pair_key and pair_key in admitted_pairs:
            kept.append(result)
            continue
        if cards >= limit:
            continue
        cards += 1
        kept.append(result)
        if pair_key:
            admitted_pairs.add(pair_key)

    return kept


def _version_num(result: dict[str, Any]) -> int:
    """Extract version number from a result dict."""
    version = result.get("version")
    if version is not None and hasattr(version, "version"):
        return version.version
    return 0


def _add_source_date(
    results: list[dict[str, Any]], search_date: date
) -> list[dict[str, Any]]:
    """Add source_date to each result for display."""
    iso = search_date.isoformat()
    for result in results:
        result["source_date"] = iso
    return results


def _unique_edition_names(results: list[dict[str, Any]]) -> list[str]:
    """Derive applicable code names from the result set."""
    seen: set[str] = set()
    names: list[str] = []
    for result in results:
        code_edition = result.get("code_edition", "")
        if code_edition and code_edition not in seen:
            seen.add(code_edition)
            names.append(code_edition)
    return names
