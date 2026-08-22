from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse
from django.test import RequestFactory
from django.utils import timezone

from core.models import EngagementEvent, SearchHistory, User
from web.middleware import RateLimitMiddleware


@pytest.mark.django_db
class TestRateLimitMiddleware:
    def setup_method(self):
        self.get_response = MagicMock(return_value=JsonResponse({"status": "ok"}))
        self.middleware = RateLimitMiddleware(self.get_response)
        self.factory = RequestFactory()

    def test_middleware_ignores_non_api(self):
        """Middleware should not interfere with non-API requests."""
        request = MagicMock()
        request.path = "/"
        response = self.middleware(request)
        assert response.status_code == 200
        self.get_response.assert_called_once()

    @patch('web.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_ignores_api_search_post(self, mock_check):
        """API endpoint is not rate-limited in middleware."""
        request = MagicMock()
        request.method = "POST"
        request.path = "/api/search"

        self.middleware(request)
        mock_check.assert_not_called()
        self.get_response.assert_called_once()

    @patch('web.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_calls_check_limit_for_htmx_search_results_post(self, mock_check):
        """Middleware should call check_rate_limit for HTMX search endpoint."""
        request = MagicMock()
        request.method = "POST"
        request.path = "/search-results/"
        mock_check.return_value = None

        self.middleware(request)
        mock_check.assert_called_once_with(request)
        self.get_response.assert_called_once()

    @patch('web.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_ignores_search_results_get(self, mock_check):
        """GET requests should not be rate limited on search endpoints."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/search-results/"

        self.middleware(request)
        mock_check.assert_not_called()
        self.get_response.assert_called_once()

    @patch('web.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_blocks_on_limit(self, mock_check):
        """Middleware should return error response when limit is hit."""
        request = MagicMock()
        request.method = "POST"
        request.path = "/search-results/"
        mock_check.return_value = JsonResponse({"error": "limit"}, status=429)

        response = self.middleware(request)
        assert response.status_code == 429
        self.get_response.assert_not_called()

    def _anonymous_htmx_request(self):
        request = self.factory.post(
            "/search-results/",
            HTTP_HX_REQUEST="true",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = AnonymousUser()
        return request

    def _spend(self, count):
        """Use up ``count`` of the allowance.

        Each row is a *different* question, and different from every question
        an earlier call wrote.  The allowance counts distinct questions, so
        identical rows would spend one search however many were written — and
        every test below that means "N searches used" would quietly be testing
        one.  Numbering from the rows already there is what makes two
        ``_spend(1)`` calls spend two.
        """
        start = SearchHistory.objects.count()
        for n in range(start, start + count):
            SearchHistory.objects.create(
                user=None,
                ip_address="127.0.0.1",
                query=f"q{n}",
                parsed_params={"date": "2010-06-01"},
                result_count=0,
                top_results=[],
            )

    def test_second_search_falls_into_the_teaser_band(self, settings):
        """Past the full-result allowance the search still runs, flagged."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 10
        self._spend(1)
        request = self._anonymous_htmx_request()

        assert self.middleware.check_rate_limit(request) is None
        assert getattr(request, "search_teaser_only", False) is True

    def test_first_search_is_not_flagged(self, settings):
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 10
        request = self._anonymous_htmx_request()

        assert self.middleware.check_rate_limit(request) is None
        assert getattr(request, "search_teaser_only", False) is False

    def test_check_rate_limit_returns_html_partial_for_htmx(self, settings):
        """Past the teaser band the search does not run; HTMX gets HTML."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 2
        self._spend(2)
        request = self._anonymous_htmx_request()

        response = self.middleware.check_rate_limit(request)

        assert response is not None
        assert response.status_code == 429
        assert response["Content-Type"].startswith("text/html")
        assert b"Daily limit reached for anonymous visitors" in response.content
        assert getattr(request, "search_teaser_only", False) is False

    def test_both_walls_record_a_block_event(self, settings):
        """The conversion denominator counts intent, not which wall it met."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 2
        self._spend(1)
        self.middleware.check_rate_limit(self._anonymous_htmx_request())
        self._spend(1)
        self.middleware.check_rate_limit(self._anonymous_htmx_request())

        blocks = EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.RATE_LIMIT_BLOCK
        ).order_by("id")
        assert [b.context["band"] for b in blocks] == ["teaser", "hard"]

    def _asking(self, query: str, day: str = ""):
        """An anonymous request that carries a question, the way the form does."""
        data = {"query": query}
        if day:
            data["date"] = day
        request = self.factory.post(
            "/search-results/", data, HTTP_HX_REQUEST="true", REMOTE_ADDR="127.0.0.1"
        )
        request.user = AnonymousUser()
        return request

    def _ask(self, query: str, day: str = ""):
        """Run one search the whole way: the check, then the row it writes."""
        request = self._asking(query, day)
        response = self.middleware.check_rate_limit(request)
        if response is None:
            SearchHistory.objects.create(
                user=None,
                ip_address="127.0.0.1",
                query=query,
                parsed_params={"date": day} if day else {},
                result_count=0,
                top_results=[],
            )
        return request, response

    def test_reading_one_answer_twice_costs_one_search(self, settings):
        """A reload, Back, or the reader's own link returns them to a search
        they already ran.  The address bar carries the search now, so this is
        one keystroke away — and it used to drop them into the teaser band
        holding results they had already been shown."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 10
        self._ask("guards", "2010-06-01")

        again, response = self._ask("guards", "2010-06-01")

        assert response is None
        assert getattr(again, "search_teaser_only", False) is False

    def test_a_second_question_still_spends_the_allowance(self, settings):
        """The allowance is not removed, only measured properly."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 10
        self._ask("guards", "2010-06-01")

        other, _ = self._ask("fire separation", "2010-06-01")

        assert getattr(other, "search_teaser_only", False) is True

    def test_the_same_words_at_another_date_are_another_question(self, settings):
        """Asking what the code said in 2005 and again in 2015 is most of what
        this product is for.  It must not be free."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 10
        self._ask("guards", "2005-01-01")

        later, _ = self._ask("guards", "2015-01-01")

        assert getattr(later, "search_teaser_only", False) is True

    def test_a_repeat_records_no_block_event(self, settings):
        """A reader re-reading one answer has not formed a second intent, and
        the conversion denominator counts intent."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 10
        self._ask("guards", "2010-06-01")
        self._ask("guards", "2010-06-01")

        assert not EngagementEvent.objects.filter(
            event_type=EngagementEvent.EventType.RATE_LIMIT_BLOCK
        ).exists()

    def test_repeats_do_not_open_the_tap(self, settings):
        """The hard band exists because the teaser costs an LLM parse per
        request.  Distinct questions still reach it."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        settings.RATE_LIMIT_ANONYMOUS_TEASER = 2
        self._ask("one", "2010-06-01")
        self._ask("two", "2010-06-01")

        _, response = self._ask("three", "2010-06-01")

        assert response is not None
        assert response.status_code == 429

    def test_authenticated_free_user_not_rate_limited(self, settings):
        """Authenticated free users should never be rate limited."""
        settings.RATE_LIMIT_AUTHENTICATED = 3
        user = User.objects.create_user(email="free@example.com", password="testpass")
        # Create more searches than the old limit
        for _ in range(10):
            SearchHistory.objects.create(
                user=user,
                query="q",
                parsed_params={},
                result_count=0,
                top_results=[],
            )
        request = self.factory.post(
            "/search-results/",
            HTTP_HX_REQUEST="true",
        )
        request.user = user
        response = self.middleware.check_rate_limit(request)
        assert response is None

    def test_yesterdays_searches_do_not_count(self, settings):
        """The daily window starts at UTC midnight; older rows are ignored."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        history = SearchHistory.objects.create(
            user=None,
            ip_address="127.0.0.1",
            query="q",
            parsed_params={},
            result_count=0,
            top_results=[],
        )
        # timestamp is auto_now_add; backdate via update()
        SearchHistory.objects.filter(pk=history.pk).update(
            timestamp=timezone.now() - timedelta(days=1)
        )
        request = self.factory.post(
            "/search-results/",
            HTTP_HX_REQUEST="true",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = AnonymousUser()

        response = self.middleware.check_rate_limit(request)
        assert response is None

    def test_invalid_forwarded_for_does_not_crash(self, settings):
        """Invalid proxy IP values should not cause DB inet errors."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        request = self.factory.post(
            "/search-results/",
            HTTP_HX_REQUEST="true",
            HTTP_X_FORWARDED_FOR="unknown",
        )
        request.user = AnonymousUser()

        response = self.middleware.check_rate_limit(request)
        assert response is None
