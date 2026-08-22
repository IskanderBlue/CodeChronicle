"""
Rate limiting middleware for search API, and the re-acceptance wall.
"""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from accounts.reacceptance import needs_reacceptance
from core.models import EngagementEvent, SearchHistory, question_keys
from shared.ip import extract_client_ip
from telemetry.events import record_event


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

            search_count = self._other_questions_today(request, ip, today_start)

            limit = settings.RATE_LIMIT_ANONYMOUS
            teaser_limit = settings.RATE_LIMIT_ANONYMOUS_TEASER

            if search_count < limit:
                return None  # Band 1: full results.

            # Every request from here up is a blocked search in the sense the
            # dashboard cares about — the visitor asked for a search they are
            # not entitled to read.  Recorded once per request, in both the
            # teaser band and the hard band, so the conversion denominator
            # counts intent rather than which wall the intent met.
            #
            # A repeat of a question already asked never reaches here, which is
            # the point: re-reading one answer is not a second intent, and
            # counting it would inflate the denominator with the same reader
            # pressing reload.  ``searches_used`` therefore counts distinct
            # other questions, not requests.
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

    def _other_questions_today(self, request, ip: str, today_start) -> int:
        """How many *different* questions this address has asked today.

        The allowance counts questions, not requests.  A reader who reloads
        their search, presses Back to it, or follows their own link to it is
        asking one question twice, and we should not charge them twice for one
        answer.  This used to count rows, so a reload spent a search — and
        since the address bar now carries the search
        (``web.views.search._push_search_url``), a repeat is one keystroke
        away.

        **A question is the query text and the date it ran at** —
        ``SearchHistory.objects.question_keys()``, the same definition
        ``web.views.history`` groups its cards on.  The same words at two
        dates are two questions; asking what the code said in 2005 and again
        in 2015 is most of what this product is for, and it must not be free.

        **The question being asked now is left out**, not counted.  Counting
        it would make the count 1 before the first search had run, and the
        first search would meet the teaser.  So the number means "how many
        other questions have you asked today", and a repeat leaves it
        unchanged.

        The distinct set is bounded: the hard band writes no row, so an
        address cannot accumulate more distinct questions than the ceiling.
        """
        asked = set(
            question_keys(
                SearchHistory.objects.filter(
                    ip_address=ip, user__isnull=True, timestamp__gte=today_start
                )
            )
        )

        # Matched against what was sent, not against a tidied copy of it: the
        # stored query is the raw posted text, and comparing a stripped value
        # to an unstripped one silently counts a repeat as a new question.
        query = request.POST.get("query", "")
        day = request.POST.get("date") or ""

        if day:
            # The picker overrides the parsed date, so the date this search
            # will run at is known here, and the match is exact.
            asked.discard((query, day))
        else:
            # No picker value, so this search runs at whatever date the parser
            # reads out of the text — which is not known until the search
            # runs.  Every earlier row with these words counts as the same
            # question.  This errs towards the reader, and only in the case
            # where they gave us no date to tell two questions apart.
            asked = {row for row in asked if row[0] != query}

        return len(asked)

    def get_client_ip(self, request):
        """Extract client IP from request, handling proxies."""
        return extract_client_ip(request.META)


class TermsReacceptanceMiddleware:
    """Send a signed-in reader to the wall when a document has moved past its
    re-acceptance floor.

    The Terms promise notice before a material change and re-acceptance at the
    next sign-in. Middleware rather than a decorator, because the promise is
    about the account and not about one page: a reader who bookmarked the
    comparison page must meet it too.

    Four paths stay open, and each for its own reason:

    * **The wall itself**, or a reader can never accept.
    * **Sign-out and the auth flow**, because refusing is allowed and a wall
      with no exit takes an account hostage.
    * **The two documents**, so a reader can read what they are accepting.
    * **``/api/``**, which authenticates with a bearer key rather than a
      session. An HTML wall is not an answer a script can act on, so a key
      holder meets the prompt the next time they use the website instead.

    Static files are not listed: they are served before this runs in
    production, and in development an unstyled wall would be worse than a
    stale stylesheet.
    """

    #: URL names whose paths are resolved once at first use.  Names rather than
    #: literal paths, so a route that moves does not silently close the wall's
    #: own door.
    EXEMPT_URL_NAMES = (
        "web:accept_terms",
        "web:terms_of_service",
        "web:privacy_policy",
    )

    #: Prefixes that stay open.  ``/accounts/`` is allauth's whole flow, which
    #: includes sign-out, and ``/api/`` is credentialed separately.
    EXEMPT_PREFIXES = ("/accounts/", "/api/")

    def __init__(self, get_response):
        self.get_response = get_response
        self._exempt_paths: set[str] | None = None

    def __call__(self, request):
        if needs_reacceptance(request) and not self._is_exempt(request.path):
            target = reverse("web:accept_terms")
            return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        if path.startswith(self.EXEMPT_PREFIXES):
            return True
        if self._exempt_paths is None:
            self._exempt_paths = {reverse(name) for name in self.EXEMPT_URL_NAMES}
        return path in self._exempt_paths
