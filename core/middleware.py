"""
Rate limiting middleware for search API.
"""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone


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
                    "upgrade_url": payload.get("upgrade_url", ""),
                },
                status=status_code,
            )
        return JsonResponse(payload, status=status_code)

    def check_rate_limit(self, request):
        """Check if user has exceeded their daily limit."""
        from core.models import SearchHistory

        today = timezone.now().date()

        if request.user.is_authenticated:
            return None  # All authenticated users are unlimited
        else:
            # Anonymous user - rate limit by IP
            ip = self.get_client_ip(request)

            search_count = SearchHistory.objects.filter(
                ip_address=ip, user__isnull=True, timestamp__date=today
            ).count()

            limit = settings.RATE_LIMIT_ANONYMOUS

            if search_count >= limit:
                payload = {
                    "error": f"Daily limit reached for anonymous users ({limit} search/day)",
                    "login_url": "/accounts/login/",
                    "signup_url": "/accounts/signup/",
                    "searches_used": search_count,
                    "limit": limit,
                }
                return self._build_rate_limit_response(request, payload, status_code=429)

        return None

    def get_client_ip(self, request):
        """Extract client IP from request, handling proxies."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
