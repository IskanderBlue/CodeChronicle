import pytest
from django.http import JsonResponse
from core.middleware import RateLimitMiddleware
from unittest.mock import MagicMock, patch

@pytest.mark.django_db
class TestRateLimitMiddleware:
    def setup_method(self):
        self.get_response = MagicMock(return_value=JsonResponse({"status": "ok"}))
        self.middleware = RateLimitMiddleware(self.get_response)

    def test_middleware_ignores_non_api(self):
        """Middleware should not interfere with non-API requests."""
        request = MagicMock()
        request.path = "/"
        response = self.middleware(request)
        assert response.status_code == 200
        self.get_response.assert_called_once()

    @patch('core.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_calls_check_limit(self, mock_check):
        """Middleware should call check_rate_limit for API search."""
        request = MagicMock()
        request.path = "/api/search"
        mock_check.return_value = None
        
        self.middleware(request)
        mock_check.assert_called_once_with(request)
        self.get_response.assert_called_once()

    @patch('core.middleware.RateLimitMiddleware.check_rate_limit')
    def test_middleware_blocks_on_limit(self, mock_check):
        """Middleware should return error response when limit is hit."""
        request = MagicMock()
        request.path = "/api/search"
        mock_check.return_value = JsonResponse({"error": "limit"}, status=429)
        
        response = self.middleware(request)
        assert response.status_code == 429
        self.get_response.assert_not_called()
