"""
Django Ninja API endpoints for CodeChronicle.
"""

import json

from ninja import NinjaAPI, Schema

api = NinjaAPI(
    title="CodeChronicle API",
    version="0.1.0",
    description="Historical Canadian Building Code Search API",
)


class ApiErrorResponse(Schema):
    success: bool
    results: list[dict] = []
    error: str
    meta: dict | None = None


class CodeRow(Schema):
    id: str
    code: str
    edition_id: str
    year: int
    name: str


class CodesResponse(Schema):
    success: bool
    results: list[CodeRow]
    error: str | None = None


class SearchResponse(Schema):
    success: bool
    results: list[dict]
    error: str | None = None
    meta: dict | None = None


class HistoryItem(Schema):
    query: str
    timestamp: str
    result_count: int


class HistoryResponse(Schema):
    success: bool
    results: list[HistoryItem]
    error: str | None = None


def _is_paid_user(user) -> bool:
    """Return True when API access is allowed for this user."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "pro_courtesy", False):
        return True
    try:
        return bool(getattr(user, "has_active_subscription", False))
    except Exception:
        return False


def _require_paid_api_access(request):
    """
    Enforce API-only access for paid users.

    Anonymous and free users should use the website UI endpoint instead.
    """
    user = request.user
    if _is_paid_user(user):
        return None

    if not getattr(user, "is_authenticated", False):
        return 401, {
            "success": False,
            "results": [],
            "error": (
                "Authentication required for direct API access. "
                "Use the website UI or sign in to a paid account."
            ),
            "meta": {"upgrade_url": "/pricing", "ui_search_url": "/"},
        }

    return 403, {
        "success": False,
        "results": [],
        "error": "Direct API access is a paid feature. Upgrade to Pro to use /api endpoints.",
        "meta": {"upgrade_url": "/pricing", "ui_search_url": "/"},
    }


def _load_code_rows_from_db() -> list[dict[str, str | int]]:
    """Primary source for code listings."""
    from core.models import CodeEdition

    editions = CodeEdition.objects.select_related("system").all()
    rows: list[dict[str, str | int]] = []
    for edition in editions:
        rows.append(
            {
                "id": edition.code_name,
                "code": edition.system.code,
                "edition_id": edition.edition_id,
                "year": edition.year,
                "name": f"{edition.system.code} {edition.year}".strip(),
            }
        )

    rows.sort(key=lambda row: str(row["name"]))
    return rows


@api.get(
    "/codes",
    response={200: CodesResponse, 401: ApiErrorResponse, 403: ApiErrorResponse, 503: ApiErrorResponse},
)
def list_codes(request):
    """List known code editions from DB-backed metadata."""
    denied = _require_paid_api_access(request)
    if denied:
        return denied

    try:
        rows = _load_code_rows_from_db()
    except Exception as exc:
        return 503, {
            "success": False,
            "results": [],
            "error": f"Code metadata is unavailable from the database: {exc}",
        }

    if not rows:
        return 503, {
            "success": False,
            "results": [],
            "error": "Code metadata is unavailable from the database.",
        }

    return {"success": True, "results": rows, "error": None}


@api.get("/health")
def health_check(request):
    """Health check endpoint."""
    return {"status": "ok"}


def _extract_query_from_request(request) -> str:
    """Support both form-encoded and JSON bodies for search payloads."""
    form_query = request.POST.get("query")
    if isinstance(form_query, str) and form_query.strip():
        return form_query.strip()

    raw_body = request.body.decode("utf-8").strip() if request.body else ""
    if not raw_body:
        return ""

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return ""

    query = body.get("query") if isinstance(body, dict) else None
    if isinstance(query, str):
        return query.strip()
    return ""


@api.post(
    "/search",
    response={200: SearchResponse, 400: ApiErrorResponse, 401: ApiErrorResponse, 403: ApiErrorResponse},
)
def search(request):
    """
    Search building codes with natural language query.
    """
    denied = _require_paid_api_access(request)
    if denied:
        return denied
    query = _extract_query_from_request(request)
    if not query:
        return 400, {
            "success": False,
            "results": [],
            "error": "Query is required.",
            "meta": None,
        }

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


@api.get("/history", response={200: HistoryResponse, 401: ApiErrorResponse, 403: ApiErrorResponse})
def get_search_history(request):
    """Return user's recent searches."""
    denied = _require_paid_api_access(request)
    if denied:
        return denied

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
