import json
from datetime import date
from unittest.mock import patch

import pytest
from django.test import Client, RequestFactory

from api.views import _extract_search_params_from_request
from core.models import ApiKey, Code, CodeEdition, User


@pytest.mark.django_db
class TestApiEndpoints:
    def setup_method(self):
        self.client = Client()
        self.free_user = User.objects.create_user(
            email="free@example.com",
            password="testpassword",
        )
        self.paid_user = User.objects.create_user(
            email="paid@example.com",
            password="testpassword",
            pro_courtesy=True,
        )
        # The API takes a key and nothing else, so every "allowed" case here
        # carries a header rather than a login.  The free account holds a key
        # too, which is the only way to test that the *subscription* is what
        # the gate reads.
        _, paid_token = ApiKey.generate(self.paid_user, "tests")
        _, free_token = ApiKey.generate(self.free_user, "tests")
        self.paid_headers = {"authorization": f"Bearer {paid_token}"}
        self.free_headers = {"authorization": f"Bearer {free_token}"}

        nbc = Code.objects.create(
            code="NBC",
            display_name="National Building Code",
            is_national=True,
        )
        CodeEdition.objects.create(
            code=nbc,
            edition_id="2025",
            year=2025,
            effective_date=date(2025, 1, 1),
        )

    def test_list_codes_requires_a_key(self):
        """A call with no key is refused, and told what to send."""
        response = self.client.get('/api/codes')
        assert response.status_code == 401
        data = response.json()
        assert data['success'] is False
        assert "API key" in data['error']

    def test_list_codes_blocks_a_free_account(self):
        """A real key on an account without Pro is refused, differently.

        401 and 403 answer different questions, and the caller acts on them
        differently: one needs a key, the other needs a subscription.
        """
        response = self.client.get('/api/codes', headers=self.free_headers)
        assert response.status_code == 403
        data = response.json()
        assert data['success'] is False
        assert "Pro subscription" in data['error']

    def test_list_codes_allows_a_paid_key(self):
        """Paid users can call direct APIs."""
        response = self.client.get('/api/codes', headers=self.paid_headers)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['results']) > 0
        assert 'NBC 2025' in [c['name'] for c in data['results']]

    def test_search_history_requires_a_key(self):
        """History API rejects a call with no key."""
        response = self.client.get('/api/history')
        assert response.status_code == 401

    def test_search_history_blocks_a_free_account(self):
        """History API is paid-only for direct API access."""
        response = self.client.get('/api/history', headers=self.free_headers)
        assert response.status_code == 403

    def test_search_history_paid_user(self):
        """Paid users can retrieve API history."""
        response = self.client.get('/api/history', headers=self.paid_headers)
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert isinstance(data['results'], list)

    def test_search_blocks_a_free_account(self):
        """Search API rejects a key held by an account without Pro."""
        response = self.client.post(
            '/api/search', {"query": "fire separation in ontario"}, headers=self.free_headers
        )
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert "Pro subscription" in data["error"]

    def test_health_is_public(self):
        """Health endpoint remains public for infra monitoring."""
        response = self.client.get('/api/health')
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"

    @patch("api.views.connection.cursor")
    def test_health_returns_503_when_database_is_unavailable(self, mock_cursor):
        """Health endpoint reports database failures to deploy smoke tests."""
        mock_cursor.side_effect = RuntimeError("database unavailable")

        response = self.client.get('/api/health')

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "error"
        assert data["database"] == "unavailable"

    @patch("services.search_service.parse_user_query", autospec=False)
    @patch("services.search_service.execute_search", autospec=False)
    @patch("services.search_service.format_search_results", autospec=False)
    def test_search_allows_paid_user(self, mock_format, mock_execute, mock_parse):
        """Paid users can call search API."""
        mock_parse.return_value = {
            "query": "fire separation",
            "province": "ON",
            "date": "2025-01-01",
        }
        mock_execute.return_value = {
            "results": [],
            "top_results_metadata": [],
            "applicable_codes": ["NBC_2025"],
        }
        mock_format.return_value = []

        response = self.client.post(
            '/api/search', {"query": "fire separation in ontario"}, headers=self.paid_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @patch("services.search_service.parse_user_query", autospec=False)
    @patch("services.search_service.execute_search", autospec=False)
    @patch("services.search_service.format_search_results", autospec=False)
    def test_search_date_province_overrides(self, mock_format, mock_execute, mock_parse):
        """date and province fields override LLM-parsed values in API search."""
        mock_parse.return_value = {"query": "fire separation", "province": "BC", "date": "2020-01-01"}
        mock_execute.return_value = {
            "results": [],
            "top_results_metadata": [],
            "applicable_codes": ["OBC_2024"],
        }
        mock_format.return_value = []

        payload = json.dumps({"query": "fire separation", "date": "1995-06-01", "province": "ON"})
        response = self.client.post(
            '/api/search',
            data=payload,
            content_type="application/json",
            headers=self.paid_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # meta reports what the search RAN at, not a separate list of what was
        # overridden.  One place to read the date and the province means a
        # caller cannot check the wrong one, and the answer is the same shape
        # whether or not the request overrode anything.
        assert data["meta"]["date"] == "1995-06-01"
        assert data["meta"]["province"] == "ON"

        # Confirm the overrides were actually passed into parse → execute pipeline
        call_kwargs = mock_parse.call_args
        # parse_user_query only receives the query string; overrides are applied after
        assert call_kwargs[0][0] == "fire separation"

        # The params dict passed to execute_search must reflect the overrides
        execute_call_args = mock_execute.call_args[0][0]
        assert execute_call_args["date"] == "1995-06-01"
        assert execute_call_args["province"] == "ON"


class TestExtractSearchParams:
    """Unit tests for _extract_search_params_from_request (no DB)."""

    def setup_method(self):
        self.factory = RequestFactory()

    def _extract(self, **kwargs):
        request = self.factory.post('/api/search', **kwargs)
        return _extract_search_params_from_request(request)

    def test_province_normalized_to_upper(self):
        params = self._extract(data={"query": "fire", "province": "on"})
        assert params["province"] == "ON"

    def test_unknown_province_dropped(self):
        params = self._extract(data={"query": "fire", "province": "ZZ"})
        assert params["province"] is None

    def test_json_province_whitelisted(self):
        params = self._extract(
            data=json.dumps({"query": "fire", "province": "bc"}),
            content_type="application/json",
        )
        assert params["province"] == "BC"

    def test_json_non_string_province_dropped(self):
        params = self._extract(
            data=json.dumps({"query": "fire", "province": 12}),
            content_type="application/json",
        )
        assert params["province"] is None

    def test_invalid_date_passed_through_for_run_search_to_reject(self):
        # run_search owns date validation and returns a correctable error;
        # dropping it here would silently fall back to the LLM-parsed date.
        params = self._extract(data={"query": "fire", "date": "not-a-date"})
        assert params["date"] == "not-a-date"
