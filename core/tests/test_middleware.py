from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse
from django.test import RequestFactory

from core.middleware import RateLimitMiddleware
from core.models import SearchHistory


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

    @patch('core.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_ignores_api_search_post(self, mock_check):
        """API endpoint is not rate-limited in middleware."""
        request = MagicMock()
        request.method = "POST"
        request.path = "/api/search"

        self.middleware(request)
        mock_check.assert_not_called()
        self.get_response.assert_called_once()

    @patch('core.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_calls_check_limit_for_htmx_search_results_post(self, mock_check):
        """Middleware should call check_rate_limit for HTMX search endpoint."""
        request = MagicMock()
        request.method = "POST"
        request.path = "/search-results/"
        mock_check.return_value = None

        self.middleware(request)
        mock_check.assert_called_once_with(request)
        self.get_response.assert_called_once()

    @patch('core.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_ignores_search_results_get(self, mock_check):
        """GET requests should not be rate limited on search endpoints."""
        request = MagicMock()
        request.method = "GET"
        request.path = "/search-results/"

        self.middleware(request)
        mock_check.assert_not_called()
        self.get_response.assert_called_once()

    @patch('core.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_blocks_on_limit(self, mock_check):
        """Middleware should return error response when limit is hit."""
        request = MagicMock()
        request.method = "POST"
        request.path = "/search-results/"
        mock_check.return_value = JsonResponse({"error": "limit"}, status=429)

        response = self.middleware(request)
        assert response.status_code == 429
        self.get_response.assert_not_called()

    def test_check_rate_limit_returns_html_partial_for_htmx(self, settings):
        """HTMX requests should get an HTML fragment, not JSON text."""
        settings.RATE_LIMIT_ANONYMOUS = 1
        SearchHistory.objects.create(
            user=None,
            ip_address="127.0.0.1",
            query="q",
            parsed_params={},
            result_count=0,
            top_results=[],
        )
        request = self.factory.post(
            "/search-results/",
            HTTP_HX_REQUEST="true",
            REMOTE_ADDR="127.0.0.1",
        )
        request.user = AnonymousUser()

        response = self.middleware.check_rate_limit(request)

        assert response is not None
        assert response.status_code == 429
        assert response["Content-Type"].startswith("text/html")
        assert b"Daily limit reached for anonymous users" in response.content

    def test_authenticated_free_user_not_rate_limited(self, settings):
        """Authenticated free users should never be rate limited."""
        from core.models import User
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
