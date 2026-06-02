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
    ProvinceCode,
    ProvisionMapping,
    RegulationClause,
)

from .engine import SEARCH_RESULT_LIMIT, compute_idf, score_versions


def execute_search(params: dict[str, Any]) -> dict[str, Any]:
    """Main search entry point.

    Queries all provision versions in force for a province at a date,
    scores them against parsed keywords, and groups transitions.
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
        "contributing_clauses__regulation",
        Prefetch(
            "provision__versions",
            queryset=CodeEditionProvisionVersion.objects
                .prefetch_related("contributing_clauses__regulation")
                .order_by("version"),
        ),
        # Next-version-not-in-force lookup for the "Next amendment" line.
        Prefetch(
            "provision__versions",
            queryset=CodeEditionProvisionVersion.objects
                .filter(effective_date__gt=search_date)
                .order_by("effective_date")[:1],
            to_attr="next_versions",
        ),
        "provision__appendix_entries__versions",
        "provision__edition__regulations",
    )

    idf_map = compute_idf(in_force_qs)

    results = score_versions(
        query=" ".join(keywords),
        versions_qs=in_force_qs,
        idf_map=idf_map,
        provision_references=provision_references,
        raw_query=params.get("raw_query", ""),
    )

    results = _group_transitions(results)
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
            for r in results[:SEARCH_RESULT_LIMIT]
        ],
    }


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
    by_provision: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        key = (result.get("id", ""), result.get("division", ""))
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

        # Both members carry the SAME new/old edition keys so the formatter
        # groups them into one bucket and distinguishes them by their own
        # ``code`` (== ``code_edition``).
        new_edition = newer.get("code_edition", "")
        old_edition = older.get("code_edition", "")
        newer["transition_context"] = {
            "is_primary": True,
            "transition_text": transition_text,
            "new_edition": new_edition,
            "old_edition": old_edition,
        }
        older["transition_context"] = {
            "is_primary": False,
            "transition_text": transition_text,
            "new_edition": new_edition,
            "old_edition": old_edition,
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

        new_edition = new_result.get("code_edition", "")
        old_edition = old_result.get("code_edition", "")
        new_result["transition_context"] = {
            "is_primary": True,
            "transition_text": transition_text,
            "new_edition": new_edition,
            "old_edition": old_edition,
            "same_edition": same_edition,
            "mapping_type": mapping.mapping_type,
        }
        old_result["transition_context"] = {
            "is_primary": False,
            "transition_text": transition_text,
            "new_edition": new_edition,
            "old_edition": old_edition,
            "same_edition": same_edition,
            "mapping_type": mapping.mapping_type,
        }
        paired_pks.add(old_pk)
        paired_pks.add(new_pk)

    return results


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
