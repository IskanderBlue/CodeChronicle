"""
Django Ninja API endpoints for CodeChronicle.
"""

from ninja import NinjaAPI
from ninja.security import django_auth

api = NinjaAPI(
    title="CodeChronicle API",
    version="0.1.0",
    description="Historical Canadian Building Code Search API",
)


@api.get("/health")
def health_check(request):
    """Health check endpoint."""
    return {"status": "ok"}


@api.post("/search")
def search(request, query: str):
    """
    Search building codes with natural language query.
    """
    from api.formatters import format_search_results
    from api.llm_parser import parse_user_query
    from api.search import execute_search
    from core.models import SearchHistory

    # Step 1: Parse natural language with LLM
    try:
        params = parse_user_query(query)
    except ValueError as e:
        return {"success": False, "results": [], "error": str(e)}

    # Step 2: Execute search
    search_results = execute_search(params)

    if "error" in search_results:
        return {"success": False, "results": [], "error": search_results["error"]}

    # Step 3: Format for display
    formatted_results = format_search_results(search_results["results"])

    # Step 4: Record the search in history
    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", ""))
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    SearchHistory.objects.create(
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        query=query,
        parsed_params=params,
        result_count=len(formatted_results),
        top_results=search_results["top_results_metadata"],
    )

    return {
        "success": True,
        "results": formatted_results,
        "error": None,
        "meta": {
            "query": query,
            "parsed_params": params,
            "applicable_codes": search_results["applicable_codes"],
            "result_count": len(formatted_results),
        },
    }


@api.get("/history", auth=django_auth)
def get_search_history(request):
    """Return user's recent searches."""
    from core.models import SearchHistory

    history = SearchHistory.objects.filter(user=request.user).order_by("-timestamp")[:20]

    results = [
        {
            "query": h.query,
            "timestamp": h.timestamp.isoformat(),
            "result_count": h.result_count,
        }
        for h in history
    ]

    return {"success": True, "results": results, "error": None}


@api.get("/codes")
def list_available_codes(request):
    """List all code editions in the system."""
    from config.code_metadata import CODE_EDITIONS

    data = []
    for code_type, editions in CODE_EDITIONS.items():
        for ed in editions:
            data.append(
                {
                    "name": f"{code_type} {ed['year']}",
                    "province": code_type if code_type != "NBC" else "Federal",
                    "status": "Current" if not ed["superseded_date"] else "Historical",
                    "effective_date": ed["effective_date"],
                }
            )

    return {"success": True, "results": data, "error": None}
