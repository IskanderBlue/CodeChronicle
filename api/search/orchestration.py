"""
Search orchestration: query provision versions in force, score, group transitions.
"""

from collections import defaultdict
from datetime import date
from typing import Any

from django.db.models import Q

from core.models import CodeEditionProvisionVersion, ProvinceCode

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

    in_force_qs = CodeEditionProvisionVersion.objects.filter(
        provision__edition__system_id__in=code_ids,
        effective_date__lte=search_date,
    ).filter(
        Q(ineffective_date__isnull=True) | Q(ineffective_date__gt=search_date)
    ).select_related(
        "provision__edition__system",
        "provision__parent",
        "clause__regulation",
    ).prefetch_related("tables")

    idf_map = compute_idf(in_force_qs)

    results = score_versions(
        query=" ".join(keywords),
        versions_qs=in_force_qs,
        idf_map=idf_map,
        provision_references=provision_references,
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

        newer["transition_context"] = {
            "is_primary": True,
            "transition_text": transition_text,
            "other_edition": older.get("code_edition", ""),
        }
        older["transition_context"] = {
            "is_primary": False,
            "transition_text": transition_text,
            "other_edition": newer.get("code_edition", ""),
        }
        output.append(newer)
        output.append(older)

    return output


def _version_num(result: dict[str, Any]) -> int:
    """Extract version number from a result dict."""
    version = result.get("version")
    if hasattr(version, "version"):
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
