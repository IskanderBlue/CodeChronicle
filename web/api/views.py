"""
Django Ninja API endpoints for CodeChronicle.

``/api/search``, ``/api/codes`` and ``/api/history`` need an API key, held by
an account with an active Pro subscription (``web.api.auth``).  ``/api/health`` and
``/api/event`` are open — the first so a monitor can reach it, the second
because it is the website's own engagement beacon.

Nothing in the website calls the three key-only endpoints, so a browser cookie
buys nothing here and is not accepted.
"""

import json
from datetime import date

from django.db import connection
from ninja import NinjaAPI, Schema

from accounts.access import edition_allowed
from core.models import CodeEdition, EngagementEvent, SearchHistory
from search.formatters.band import parse_iso_date
from search.service import PROVINCE_NAMES, run_search
from shared.ip import extract_client_ip
from telemetry.events import record_event
from web.api.auth import apply_search_throttle, require_api_key
from web.api.provisions import find_provision, provision_out, record_fetch, version_in_force
from web.api.schemas import (
    ProvisionMetaOut,
    ProvisionOut,
    ResultOut,
    SearchMetaOut,
    flatten,
    result_out,
)

api = NinjaAPI(
    title="CodeChronicle API",
    version="0.1.0",
    description=(
        "Historical Canadian Building Code search. "
        "Authenticate with an API key issued from your CodeChronicle settings "
        "page, sent as `Authorization: Bearer <key>`. An active Pro "
        "subscription is required. `/health` needs no key."
    ),
)


class ApiErrorResponse(Schema):
    """Every refusal, in the same envelope as an answer.

    ``results`` is always empty and is kept so one client can read a refusal
    and an answer with the same code.  ``meta`` carries the links a caller
    acts on (where the docs are, where keys are made, where to subscribe),
    which is why it is not the search's ``meta``.
    """

    success: bool
    results: list[ResultOut] = []
    error: str
    meta: dict[str, str] | None = None


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
    """One entry per matched provision, most relevant first."""

    success: bool
    results: list[ResultOut]
    error: str | None = None
    meta: SearchMetaOut | None = None


class HealthResponse(Schema):
    status: str
    database: str
    detail: str | None = None


class HistoryItem(Schema):
    query: str
    timestamp: str
    result_count: int


class HistoryResponse(Schema):
    success: bool
    results: list[HistoryItem]
    error: str | None = None


class EventPayload(Schema):
    event_type: str
    object_type: str = ""
    object_id: int | None = None
    search_id: int | None = None
    context: dict = {}


class EventResponse(Schema):
    success: bool
    error: str | None = None


#: Where a caller goes when a provision is not there or not theirs.  The list
#: of editions is the useful answer to both: it says what this account can ask
#: for, which is what a wrong edition key and a locked edition both need.
_NOT_FOUND_HELP = {"editions_url": "/api/codes", "docs_url": "/api/docs"}


def _load_code_rows_from_db() -> list[dict[str, str | int]]:
    """Primary source for code listings."""
    editions = CodeEdition.objects.select_related("code").all()
    rows: list[dict[str, str | int]] = []
    for edition in editions:
        rows.append(
            {
                "id": edition.code_name,
                "code": edition.code.code,
                "edition_id": edition.edition_id,
                "year": edition.year,
                "name": f"{edition.code.code} {edition.year}".strip(),
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
    denied = require_api_key(request)
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


@api.get("/health", response={200: HealthResponse, 503: HealthResponse})
def health_check(request):
    """Health check endpoint."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return 503, {"status": "error", "database": "unavailable", "detail": str(exc)}

    return {"status": "ok", "database": "ok"}


def _normalize_province(value: str | None) -> str | None:
    """Uppercase a province override; drop anything not a known code.

    ``date`` gets no such treatment here on purpose — ``run_search``
    validates it and returns a correctable message, whereas a silently
    dropped override would fall back to the LLM-parsed date.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    code = value.strip().upper()
    return code if code in PROVINCE_NAMES else None


def _extract_search_params_from_request(request) -> dict[str, str | None]:
    """
    Extract query, date, and province from form-encoded or JSON bodies.

    Returns a dict with keys ``query``, ``date``, and ``province``.
    ``query`` is an empty string when absent; the other two are ``None``.
    ``province`` is normalized to a known upper-case two-letter code or
    ``None``.
    """
    params: dict[str, str | None] = {"query": "", "date": None, "province": None}

    # Form-encoded body takes priority (matches UI behaviour)
    form_query = request.POST.get("query")
    if isinstance(form_query, str) and form_query.strip():
        params["query"] = form_query.strip()
        params["date"] = request.POST.get("date") or None
        params["province"] = _normalize_province(request.POST.get("province"))
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

    params["province"] = _normalize_province(body.get("province"))

    return params


@api.post(
    "/search",
    response={
        200: SearchResponse,
        400: ApiErrorResponse,
        401: ApiErrorResponse,
        403: ApiErrorResponse,
        429: ApiErrorResponse,
    },
)
def search(request):
    """
    Search building codes with natural language query.

    Optional JSON body fields:
      - ``date`` (YYYY-MM-DD): overrides the LLM-parsed construction date.
      - ``province`` (two-letter code, e.g. "ON"): overrides the LLM-parsed province.
    """
    denied = require_api_key(request)
    if denied:
        return denied

    # Only the search carries a daily allowance: it costs a language-model
    # parse and answers with up to a hundred provisions.  Past the allowance
    # the search still runs, after a wait that grows with the overage — it
    # never refuses.  Applied before the query is read, so a caller over the
    # line waits the same whatever they sent.
    apply_search_throttle(request)

    search_params = _extract_search_params_from_request(request)
    query = search_params["query"]
    if not query:
        return 400, {
            "success": False,
            "results": [],
            "error": "Query is required.",
            "meta": None,
        }

    ip = extract_client_ip(request.META)

    result = run_search(
        query,
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip if not request.user.is_authenticated else None,
        date_override=search_params["date"],
        province_override=search_params["province"],
        # Stamps the history row, which is both what the daily ceiling counts
        # and what makes a run of automated searches recognisable as one.
        source=SearchHistory.Source.API,
    )

    if not result["success"]:
        return {"success": False, "results": [], "error": result["error"]}

    # The page's cards come apart into one entry per matched provision, and
    # each is projected onto ``ResultOut``.  Both steps live in ``web.api.schemas``
    # so ``/api/docs`` describes exactly what a caller receives.
    rows = [result_out(card) for card in flatten(result["results"])]
    parsed = result["parsed_params"] or {}
    return {
        "success": True,
        "results": rows,
        "error": None,
        # What ran, not what was asked: an explicit ``date`` or ``province``
        # in the request overrides the parser, and a caller that cannot see
        # which date was used cannot check the answer.
        "meta": {
            "query": query,
            "date": search_params["date"] or parsed.get("date"),
            "province": search_params["province"] or parsed.get("province") or "",
            "keywords": parsed.get("keywords") or [],
            "editions_searched": result["applicable_codes"],
            "result_count": len(rows),
        },
    }


@api.get("/history", response={200: HistoryResponse, 401: ApiErrorResponse, 403: ApiErrorResponse})
def get_search_history(request):
    """Return user's recent searches."""
    denied = require_api_key(request)
    if denied:
        return denied

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


@api.post("/event", response={200: EventResponse, 400: EventResponse})
def record_engagement(request, payload: EventPayload):
    """Beacon endpoint for client-fired engagement events.

    Covers result interactions that have no server round-trip of their own —
    following an external source link, a PDF download — and attributes them to
    the originating search via ``search_id``.  Deliberately **not** gated by
    ``require_api_key``: tracking applies to all users, anonymous
    included.  It executes no search, so ``RateLimitMiddleware`` (which only
    guards ``/search-results/``) leaves it untouched.
    """
    valid = {choice.value for choice in EngagementEvent.EventType}
    if payload.event_type not in valid:
        return 400, {"success": False, "error": f"Unknown event_type: {payload.event_type}"}

    record_event(
        request,
        event_type=payload.event_type,
        object_type=payload.object_type,
        object_id=payload.object_id,
        search_id=payload.search_id,
        context=payload.context,
    )
    return {"success": True, "error": None}


class ProvisionResponse(Schema):
    """One provision version, with its text."""

    success: bool
    #: A list of one, so a caller reads a provision and a search with the same
    #: code. Empty on a refusal.
    results: list[ProvisionOut] = []
    error: str | None = None
    meta: ProvisionMetaOut | None = None


@api.get(
    "/provision",
    response={
        200: ProvisionResponse,
        400: ApiErrorResponse,
        401: ApiErrorResponse,
        403: ApiErrorResponse,
        404: ApiErrorResponse,
    },
)
def get_provision(
    request,
    edition: str,
    id: str,
    division: str = "",
    on: str = "",
    version: int | None = None,
):
    """Fetch one provision, as it read on a date.

    The arguments are the fields a search result already carries, so a caller
    loops over results and asks for the ones worth reading without composing
    anything. They are query parameters rather than path segments because a
    division-less edition has an empty division, and an empty path segment is
    not a path.

    Name **either** ``on`` (a date, and the usual way to ask — "what did this
    say when the building was built") **or** ``version`` (an exact version
    number, for pinning a citation). Naming neither reads as today.

    This is the only endpoint that serves provision text, and every text it
    serves is recorded against the account (``core.models.ProvisionFetch``).
    """
    denied = require_api_key(request)
    if denied:
        return denied

    if on and version is not None:
        return 400, {
            "success": False,
            "error": (
                "Name either 'on' (a date) or 'version' (a number), not both. "
                "They can disagree, and we will not guess which you meant."
            ),
            "meta": None,
        }

    provision = find_provision(edition, division, id)
    if provision is None:
        return 404, {
            "success": False,
            "error": (
                f"No provision {id!r} in {edition!r}"
                + (f" division {division!r}." if division else ".")
            ),
            "meta": _NOT_FOUND_HELP,
        }

    # The same gate as every other surface. An API key never widens what an
    # account may read; it only changes how the account asks.
    if not edition_allowed(request.user, provision.edition.code_name):
        return 403, {
            "success": False,
            "error": f"{provision.edition.code_name} is not included in this plan.",
            "meta": _NOT_FOUND_HELP,
        }

    # The two ways of naming a version, and each branch owns everything it
    # needs — which is also why ``as_of`` is set in one of them rather than
    # ahead of both: a date only means anything when no version was named.
    as_of: date | None = None
    if version is not None:
        target = provision.versions.filter(version=version).first()
        resolved_by = "requested"
    else:
        as_of = parse_iso_date(on) if on else date.today()
        if as_of is None:
            return 400, {
                "success": False,
                "error": f"'{on}' is not a date. Use YYYY-MM-DD.",
                "meta": None,
            }
        target = version_in_force(provision, as_of)
        resolved_by = "in_force_on"

    if target is None:
        return 404, {
            "success": False,
            "error": (
                f"No version {version} of {id}."
                if version is not None
                else f"Nothing governed {id} on {as_of}."
            ),
            "meta": _NOT_FOUND_HELP,
        }

    record_fetch(request.user, target)
    return {
        "success": True,
        "results": [provision_out(target)],
        "error": None,
        "meta": {
            "on": as_of.isoformat() if as_of is not None else None,
            "resolved_by": resolved_by,
            "version_count": provision.versions.count(),
        },
    }
