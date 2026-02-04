import pytest
from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()

@pytest.mark.django_db
class TestApiEndpoints:
    def setup_method(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpassword",
            username="testuser"
        )

    def test_list_codes(self):
        """Test the /api/codes endpoint."""
        response = self.client.get('/api/codes')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['results']) > 0
        assert 'NBC 2025' in [c['name'] for c in data['results']]

    def test_search_history_auth_required(self):
        """Test that history requires authentication."""
        response = self.client.get('/api/history')
        assert response.status_code == 401

    def test_search_history_authenticated(self):
        """Test history retrieval for logged-in user."""
        self.client.force_login(self.user)
        response = self.client.get('/api/history')
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert isinstance(data['results'], list)
