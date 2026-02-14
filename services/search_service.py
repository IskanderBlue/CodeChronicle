"""
HTTP-agnostic search service that consolidates the shared logic
between core/views.py (HTMX) and api/views.py (Django Ninja).
"""

from typing import Any

from coloured_logger import Logger

from api.formatters import format_search_results
from api.llm_parser import parse_user_query
from api.search import execute_search
from core.models import SearchHistory

logger = Logger(__name__)


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
        parsed_params, and top_results_metadata.
    """
    try:
        # Step 1: Parse natural language with LLM
        params = parse_user_query(query)

        # Apply manual overrides
        if date_override:
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

        # Step 3: Format results for display
        formatted = format_search_results(search_data["results"])
        logger.info("search service payload: %d results", len(formatted))

        # Step 4: Record search history (non-fatal)
        try:
            SearchHistory.objects.create(
                user=user,
                ip_address=ip_address if user is None else None,
                query=query,
                parsed_params=params,
                result_count=len(formatted),
                top_results=search_data.get("top_results_metadata", []),
            )
        except Exception as e:
            logger.error("Error recording search history: %s", e)

        return {
            "success": True,
            "results": formatted,
            "error": None,
            "applicable_codes": search_data.get("applicable_codes", []),
            "parsed_params": params,
            "top_results_metadata": search_data.get("top_results_metadata", []),
        }

    except Exception as e:
        error_msg = str(e)
        # Surface a friendlier message for Anthropic auth failures
        if "401" in error_msg and "invalid x-api-key" in error_msg.lower():
            error_msg = (
                "Search engine authentication failure. "
                "Please check the ANTHROPIC_API_KEY in .env settings."
            )
        logger.error("Search service error: %s", error_msg)
        return {
            "success": False,
            "error": f"An unexpected error occurred: {error_msg}",
            "results": [],
        }
