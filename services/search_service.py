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
from config.part_applicability import DEFAULT_AREA_UNIT, Building, coerce_building
from config.search_limits import CLOSE_MATCH_THRESHOLD, coerce_match_threshold
from core.access import allowed_edition_names
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
    match_threshold: float = CLOSE_MATCH_THRESHOLD,
    building: Building | None = None,
    source: str = SearchHistory.Source.WEB,
) -> dict[str, Any]:
    """
    Execute a full search pipeline: parse → search → format → save history.

    Args:
        query: Natural-language search query.
        user: Django User instance (None for anonymous).
        ip_address: Client IP for anonymous tracking.
        date_override: If provided, overrides the LLM-parsed date (YYYY-MM-DD).
        province_override: If provided, overrides the LLM-parsed province code.
        match_threshold: Relevance floor for a close match; clamped to a
            storable floor.
        building: What the reader told us about their building —
            ``occupancy`` (which overrides the parser's reading of the query),
            ``storeys`` and ``area_m2`` (which the parser never supplies, see
            ``api.llm_parser``).  Ranking only: the orchestrator prefers the
            part the code says governs such a building, and nothing here
            reaches the scored keywords.  Absent keys leave the parser's
            answer, and an absent occupancy means no preference at all.
        source: Which surface ran the search, stamped on the ``SearchHistory``
            row.  The API's daily quota counts its own rows, and a run of
            automated searches is only recognisable as one if the rows say
            where they came from.

    Returns:
        A dict with keys: success, results, error, applicable_codes,
        parsed_params, top_results_metadata, match_threshold,
        weak_matches_only, accessible_match_count, close_match_count,
        score_buckets, and the free-tier teaser's locked_editions
        ({edition: match count}) / locked_preview (identity-only rows).
    """
    match_threshold = coerce_match_threshold(match_threshold)
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

        # The building the reader is asking about.
        #
        # **The model only ever fills a blank.**  ``building`` carries a key
        # only when the reader supplied a usable value (``coerce_building``
        # drops everything else), so a stated occupancy overwrites whatever the
        # parser read out of the query text, and a blank one leaves the
        # parser's reading in place.  That is the whole contract of the
        # BUILDING strip's "Read from my query" option, and it runs in this
        # direction — reader over model — for the same reason the AS-OF picker
        # overrides the parsed date.
        #
        # ``storeys`` and ``area_m2`` have no parser value to overwrite. The
        # tool schema does not offer them and the prompt forbids reporting a
        # size, because a measurement is a fact about a building rather than a
        # word in a question, and a guess at one is silently wrong.
        #
        # Written into ``params`` rather than passed beside it, so it lands in
        # ``parsed_params`` on the SearchHistory row and the history link
        # replays the ranking the reader last set.
        params.update(building or {})

        # Step 2: Execute search.  The free-tier scope goes *in* rather than
        # being applied to the output: the orchestrator splits by access before
        # trimming, so a gated searcher's cards are filled with editions they
        # can open instead of being whatever survived someone else's top ten.
        # It comes back already-scoped, with exact per-edition counts for the
        # teaser.
        search_data = execute_search(
            params,
            allowed_editions=allowed_edition_names(user),
            match_threshold=match_threshold,
        )

        if "error" in search_data:
            return {
                "success": False,
                "error": search_data["error"],
                "results": [],
            }

        raw_results = search_data["results"]
        locked_editions = search_data.get("locked_editions") or {}
        applicable_codes = search_data.get("applicable_codes", [])
        top_results_metadata = search_data.get("top_results_metadata", [])

        # Step 3: Format results for display. The parsed/overridden query
        # date drives the IN FORCE band's query tick + coverage; the parsed
        # keywords are highlighted in the provision body.
        formatted = format_search_results(
            raw_results,
            query_date=params.get("date"),
            terms=params.get("keywords"),
            user=user,
            # Re-coerced from the merged params rather than passed through, so
            # the sentence describes exactly what the ranking used — including
            # an occupancy the parser supplied and the reader never typed.
            building=coerce_building(
                params.get("occupancy"),
                params.get("storeys"),
                params.get("area"),
                params.get("area_unit") or DEFAULT_AREA_UNIT,
            ),
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
                source=source,
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
            # {edition code_name: match count} for the free-tier teaser —
            # exact totals over the whole scored corpus, not the display pool,
            # so the notice can name a real number.  Empty for Pro.
            "locked_editions": locked_editions,
            # Identity-only rows (id / division / title) behind the collapsed
            # "more results on Pro" disclosure, capped upstream.
            "locked_preview": search_data.get("locked_preview") or [],
            # Accessible matches in total; > len(results) means the
            # results-per-search control still has something to reveal.
            "accessible_match_count": search_data.get("accessible_match_count", 0),
            "match_threshold": match_threshold,
            # Nothing cleared the floor, so the weak matches are shown anyway —
            # the UI says so rather than passing them off as close.
            "weak_matches_only": search_data.get("weak_matches_only", False),
            # Score distribution the threshold control is drawn over.
            "score_buckets": search_data.get("score_buckets") or [],
            "score_bucket_width": search_data.get("score_bucket_width"),
            # Matches above the line, before any weak-match fallback replaced
            # the list — what the threshold control reports as kept.
            "close_match_count": search_data.get("close_match_count", 0),
            # True only when SEARCH_RESULT_CAP trimmed rows.
            "cap_binds": search_data.get("cap_binds", False),
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
