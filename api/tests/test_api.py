from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from core.models import CodeEdition, CodeSystem

User = get_user_model()

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
        nbc = CodeSystem.objects.create(
            code="NBC",
            display_name="National Building Code",
            is_national=True,
        )
        CodeEdition.objects.create(
            system=nbc,
            edition_id="2025",
            year=2025,
            map_codes=["NBC"],
            effective_date=date(2025, 1, 1),
        )

    def test_list_codes_requires_authentication(self):
        """Anonymous users cannot call direct APIs."""
        response = self.client.get('/api/codes')
        assert response.status_code == 401
        data = response.json()
        assert data['success'] is False
        assert "Authentication required" in data['error']

    def test_list_codes_blocks_free_user(self):
        """Logged-in free users are blocked from direct APIs."""
        self.client.force_login(self.free_user)
        response = self.client.get('/api/codes')
        assert response.status_code == 403
        data = response.json()
        assert data['success'] is False
        assert "paid feature" in data['error']

    def test_list_codes_allows_paid_user(self):
        """Paid users can call direct APIs."""
        self.client.force_login(self.paid_user)
        response = self.client.get('/api/codes')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['results']) > 0
        assert 'NBC 2025' in [c['name'] for c in data['results']]

    def test_search_history_requires_authentication(self):
        """History API rejects anonymous users."""
        response = self.client.get('/api/history')
        assert response.status_code == 401

    def test_search_history_blocks_free_user(self):
        """History API is paid-only for direct API access."""
        self.client.force_login(self.free_user)
        response = self.client.get('/api/history')
        assert response.status_code == 403

    def test_search_history_paid_user(self):
        """Paid users can retrieve API history."""
        self.client.force_login(self.paid_user)
        response = self.client.get('/api/history')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert isinstance(data['results'], list)

    def test_search_blocks_free_user(self):
        """Search API rejects free users."""
        self.client.force_login(self.free_user)
        response = self.client.post('/api/search', {"query": "fire separation in ontario"})
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert "paid feature" in data["error"]

    def test_health_is_public(self):
        """Health endpoint remains public for infra monitoring."""
        response = self.client.get('/api/health')
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @patch("services.search_service.parse_user_query", autospec=False)
    @patch("services.search_service.execute_search", autospec=False)
    @patch("services.search_service.format_search_results", autospec=False)
    def test_search_allows_paid_user(self, mock_format, mock_execute, mock_parse):
        """Paid users can call search API."""
        self.client.force_login(self.paid_user)
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

        response = self.client.post('/api/search', {"query": "fire separation in ontario"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
