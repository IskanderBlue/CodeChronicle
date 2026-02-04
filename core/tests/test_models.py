import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from core.models import SearchHistory

User = get_user_model()

@pytest.mark.django_db
class TestSearchHistory:
    def setup_method(self):
        self.user = User.objects.create_user(
            email="history@example.com",
            password="password",
            username="historyuser"
        )

    def test_create_history(self):
        """Test creating a search history entry."""
        entry = SearchHistory.objects.create(
            user=self.user,
            query="fire safety",
            parsed_params={'keywords': ['fire']},
            result_count=5
        )
        assert entry.id is not None
        assert entry.user == self.user
        assert entry.timestamp <= timezone.now()

    def test_anonymous_history(self):
        """Test creating history for anonymous user."""
        entry = SearchHistory.objects.create(
            ip_address="127.0.0.1",
            query="anonymous search",
            result_count=0
        )
        assert entry.user is None
        assert entry.ip_address == "127.0.0.1"
