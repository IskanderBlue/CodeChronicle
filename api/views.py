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


def _extract_search_params_from_request(request) -> dict[str, str | None]:
    """
    Extract query, date, and province from form-encoded or JSON bodies.

    Returns a dict with keys ``query``, ``date``, and ``province``.
    ``query`` is an empty string when absent; the other two are ``None``.
    """
    params: dict[str, str | None] = {"query": "", "date": None, "province": None}

    # Form-encoded body takes priority (matches UI behaviour)
    form_query = request.POST.get("query")
    if isinstance(form_query, str) and form_query.strip():
        params["query"] = form_query.strip()
        params["date"] = request.POST.get("date") or None
        params["province"] = request.POST.get("province") or None
        return params

    raw_body = request.body.decode("utf-8").strip() if request.body else ""
    if not raw_body:
        return params

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        return params

    if not isinstance(body, dict):
        return params

    query = body.get("query")
    if isinstance(query, str):
        params["query"] = query.strip()

    date = body.get("date")
    if isinstance(date, str) and date.strip():
        params["date"] = date.strip()

    province = body.get("province")
    if isinstance(province, str) and province.strip():
        params["province"] = province.strip()

    return params


@api.post(
    "/search",
    response={200: SearchResponse, 400: ApiErrorResponse, 401: ApiErrorResponse, 403: ApiErrorResponse},
)
def search(request):
    """
    Search building codes with natural language query.

    Optional JSON body fields:
      - ``date`` (YYYY-MM-DD): overrides the LLM-parsed construction date.
      - ``province`` (two-letter code, e.g. "ON"): overrides the LLM-parsed province.
    """
    denied = _require_paid_api_access(request)
    if denied:
        return denied

    search_params = _extract_search_params_from_request(request)
    query = search_params["query"]
    if not query:
        return 400, {
            "success": False,
            "results": [],
            "error": "Query is required.",
            "meta": None,
        }

    from services.search_service import run_search

    ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", ""))
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()

    result = run_search(
        query,
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        date_override=search_params["date"],
        province_override=search_params["province"],
    )

    if not result["success"]:
        return {"success": False, "results": [], "error": result["error"]}

    overrides = {
        k: v
        for k, v in {"date": search_params["date"], "province": search_params["province"]}.items()
        if v is not None
    }
    return {
        "success": True,
        "results": result["results"],
        "error": None,
        "meta": {
            "query": query,
            "parsed_params": result["parsed_params"],
            "applicable_codes": result["applicable_codes"],
            "result_count": len(result["results"]),
            **({"overrides": overrides} if overrides else {}),
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
