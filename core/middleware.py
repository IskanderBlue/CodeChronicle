"""
Rate limiting middleware for search API.
"""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.events import record_event
from core.ip_utils import extract_client_ip
from core.models import EngagementEvent, SearchHistory


class RateLimitMiddleware:
    """
    Enforce rate limits on search API endpoints.

    Limits:
    - Anonymous users: RATE_LIMIT_ANONYMOUS per day (per IP)
    - Authenticated users: Unlimited
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only apply to write search endpoints.
        if request.method == "POST" and self._is_limited_search_path(request.path):
            error_response = self.check_rate_limit(request)
            if error_response:
                return error_response

        return self.get_response(request)

    def _is_limited_search_path(self, path: str) -> bool:
        """Return True for UI endpoints that execute a new search."""
        return path.startswith("/search-results/")

    def _build_rate_limit_response(self, request, payload: dict, status_code: int):
        """Return HTMX-friendly HTML or JSON for API clients."""
        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx:
            return render(
                request,
                "partials/search_results_partial.html",
                {
                    "success": False,
                    "error": payload["error"],
                    "rate_limited": True,
                    "signup_url": payload.get("signup_url", ""),
                    "login_url": payload.get("login_url", ""),
                },
                status=status_code,
            )
        return JsonResponse(payload, status=status_code)

    def check_rate_limit(self, request):
        """Decide which of three bands this anonymous request falls in.

        Returns a response only for the hard block.  The middle band —
        "teaser" — returns ``None`` and sets ``request.search_teaser_only``,
        so the search view runs the search and withholds the text rather than
        the middleware refusing before anything is known about the query.
        """
        # Range filter instead of __date so the timestamp index serves the
        # count (__date casts the column). Day boundary is UTC midnight,
        # matching what __date did under TIME_ZONE="UTC".
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if request.user.is_authenticated:
            return None  # All authenticated users are unlimited
        else:
            # Anonymous user - rate limit by IP
            ip = self.get_client_ip(request)
            if not ip:
                return None

            search_count = SearchHistory.objects.filter(
                ip_address=ip, user__isnull=True, timestamp__gte=today_start
            ).count()

            limit = settings.RATE_LIMIT_ANONYMOUS
            teaser_limit = settings.RATE_LIMIT_ANONYMOUS_TEASER

            if search_count < limit:
                return None  # Band 1: full results.

            # Every request from here up is a blocked search in the sense the
            # dashboard cares about — the visitor asked for a search they are
            # not entitled to read.  Recorded once per request, in both the
            # teaser band and the hard band, so the conversion denominator
            # counts intent rather than which wall the intent met.
            record_event(
                request,
                event_type=EngagementEvent.EventType.RATE_LIMIT_BLOCK,
                context={
                    "searches_used": search_count,
                    "limit": limit,
                    "band": "teaser" if search_count < teaser_limit else "hard",
                },
            )

            if search_count < teaser_limit:
                # Band 2: run the search, withhold the text.  The view reads
                # this flag; the middleware does not run searches itself.
                request.search_teaser_only = True
                return None

            # Band 3: the search does not run.
            payload = {
                "error": (
                    f"Daily limit reached for anonymous visitors "
                    f"({teaser_limit} searches/day)"
                ),
                "login_url": "/accounts/login/",
                "signup_url": "/accounts/signup/",
                "searches_used": search_count,
                "limit": teaser_limit,
            }
            return self._build_rate_limit_response(request, payload, status_code=429)

        return None

    def get_client_ip(self, request):
        """Extract client IP from request, handling proxies."""
        return extract_client_ip(request.META)
