"""
HTTP-agnostic search service that consolidates the shared logic
between core/views.py (HTMX) and api/views.py (Django Ninja).
"""

from datetime import date
from typing import Any

import anthropic
from coloured_logger import Logger

from api.formatters import format_search_results
from api.llm_parser import parse_user_query
from api.search import execute_search
from core.access import partition_results
from core.models import CorpusCurrency, SearchHistory

logger = Logger(__name__)

# Full province names for the "we don't cover X yet" notice (the LLM emits
# two-letter codes; users read prose).
PROVINCE_NAMES = {
    "ON": "Ontario",
    "BC": "British Columbia",
    "AB": "Alberta",
    "QC": "Quebec",
    "MB": "Manitoba",
    "SK": "Saskatchewan",
    "NS": "Nova Scotia",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island",
    "YT": "Yukon",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
}

# Jurisdictions we actually have a code corpus for. Everything else triggers
# the "not yet" notice. Expansion is a medium/long-range plan — see the pricing
# page roadmap.
COVERED_PROVINCES = {"ON"}


def run_search(
    query: str,
    *,
    user=None,
    ip_address: str | None = None,
    date_override: str | None = None,
    province_override: str | None = None,
) -> dict[str, Any]:
    """
    Execute a full search pipeline: parse → search → format → save history.

    Args:
        query: Natural-language search query.
        user: Django User instance (None for anonymous).
        ip_address: Client IP for anonymous tracking.
        date_override: If provided, overrides the LLM-parsed date (YYYY-MM-DD).
        province_override: If provided, overrides the LLM-parsed province code.

    Returns:
        A dict with keys: success, results, error, applicable_codes,
        parsed_params, top_results_metadata, and locked_editions (the
        free-tier gate's {edition: dropped count} teaser counts).
    """
    try:
        # Step 1: Parse natural language with LLM
        params = parse_user_query(query)
        # The raw text lets the scorer tell which keywords the user actually
        # typed (direct) from those the LLM expanded in (indirect, 0.9 weight).
        params["raw_query"] = query

        # Capture what the LLM detected *from the query text* before the form
        # overrides (jurisdiction is hard-locked to ON, the as-of picker always
        # posts a date) overwrite it. This is what lets us tell the user "you
        # asked about X, which we don't cover" instead of silently searching
        # Ontario / the picker date as if they'd asked for it.
        llm_province = params.get("province", "ON")
        llm_date_str = params.get("date")

        # Coverage window (real dates, snapshotted at data load). Used both to
        # phrase the out-of-range message and to decide whether the user's
        # explicitly-named date is searchable at all.
        currency = CorpusCurrency.get_solo()
        coverage_start = currency.coverage_start if currency else None
        coverage_end = currency.coverage_end if currency else None

        # A jurisdiction we don't cover yet — surfaced as a non-blocking notice;
        # the search still runs against Ontario so the user gets *something*.
        not_covered_province: str | None = None
        if llm_province and llm_province not in COVERED_PROVINCES:
            not_covered_province = PROVINCE_NAMES.get(llm_province, llm_province)

        # A date the user explicitly named (not the parser's "no date -> today"
        # default) that falls outside our coverage. Don't blow smoke by
        # answering at the in-range picker date — say we don't have it and stop.
        date_explicit = bool(llm_date_str) and llm_date_str != date.today().isoformat()
        if date_explicit and coverage_start and coverage_end:
            try:
                named = date.fromisoformat(llm_date_str or "")
            except ValueError:
                named = None
            if named and (named < coverage_start or named > coverage_end):
                return {
                    "success": True,
                    "results": [],
                    "error": None,
                    "applicable_codes": [],
                    "parsed_params": params,
                    "date_out_of_range": llm_date_str,
                    "not_covered_province": not_covered_province,
                    "search_history_id": None,
                }

        # Apply manual overrides. The date override is the one piece of raw
        # user input that reaches the date math, so validate it here and return
        # a specific, correctable message rather than letting
        # ``date.fromisoformat`` raise deep in execute_search (which would
        # surface as a cryptic "unexpected error"). ``invalid_date`` lets the
        # template point the user back at the date selector.
        if date_override:
            try:
                date.fromisoformat(date_override)
            except ValueError:
                return {
                    "success": False,
                    "error": (
                        f'"{date_override}" is not a valid date. Please pick a '
                        "date with the date selector (YYYY-MM-DD) and search again."
                    ),
                    "results": [],
                    "invalid_date": date_override,
                }
            params["date"] = date_override
        if province_override:
            params["province"] = province_override

        # Step 2: Execute search
        search_data = execute_search(params)

        if "error" in search_data:
            return {
                "success": False,
                "error": search_data["error"],
                "results": [],
            }

        # Free-tier content gate (inert unless FREE_TIER_GATING_ENABLED):
        # drop results from editions outside the user's scope BEFORE
        # formatting, keeping per-edition counts so the UI renders a teaser
        # ("N results in OBC 2012 — available on Pro") rather than silently
        # returning less.  The formatter already renders a transition pair
        # whose other member was dropped as a plain result, so cross-edition
        # pairs degrade safely.
        raw_results, locked_editions = partition_results(user, search_data["results"])
        applicable_codes = [
            c for c in search_data.get("applicable_codes", []) if c not in locked_editions
        ]
        top_results_metadata = [
            m
            for m in search_data.get("top_results_metadata", [])
            if m.get("code") not in locked_editions
        ]

        # Step 3: Format results for display. The parsed/overridden query
        # date drives the IN FORCE band's query tick + coverage; the parsed
        # keywords are highlighted in the provision body.
        formatted = format_search_results(
            raw_results,
            query_date=params.get("date"),
            terms=params.get("keywords"),
            user=user,
        )
        logger.info("search service payload: %d results", len(formatted))

        # Step 4: Record search history (non-fatal).  The row id is surfaced
        # so engagement events (provision views, link clicks) can attribute
        # back to the search that produced them — see core.events.
        search_history_id: int | None = None
        try:
            history = SearchHistory.objects.create(
                user=user,
                ip_address=ip_address if user is None else None,
                query=query,
                parsed_params=params,
                result_count=len(formatted),
                top_results=top_results_metadata,
            )
            search_history_id = history.pk
        except Exception as e:
            logger.error("Error recording search history: %s", e)

        return {
            "success": True,
            "results": formatted,
            "error": None,
            "applicable_codes": applicable_codes,
            "parsed_params": params,
            "top_results_metadata": top_results_metadata,
            "search_history_id": search_history_id,
            # Non-blocking: the search ran against Ontario, but the user asked
            # about a jurisdiction we don't cover yet — tell them.
            "not_covered_province": not_covered_province,
            # {edition code_name: dropped result count} for the free-tier
            # teaser notice; empty for unrestricted users / gating off.
            "locked_editions": locked_editions,
        }

    except (ValueError, anthropic.APIError) as e:
        # Known failure modes: bad input reaching pipeline internals, or the
        # Anthropic API failing (auth, rate limit, overload).
        error_msg = str(e)
        # Surface a friendlier message for Anthropic auth failures
        if isinstance(e, anthropic.AuthenticationError) or (
            "401" in error_msg and "invalid x-api-key" in error_msg.lower()
        ):
            error_msg = (
                "Search engine authentication failure. "
                "Please check the ANTHROPIC_API_KEY in .env settings."
            )
        logger.error("Search service error: %s", error_msg)
        return {
            "success": False,
            "error": f"Search failed: {error_msg}",
            "results": [],
        }
    except Exception as e:
        logger.error("Unexpected search service error: %s", e, exc_info=True)
        return {
            "success": False,
            "error": f"An unexpected error occurred: {e}",
            "results": [],
        }
