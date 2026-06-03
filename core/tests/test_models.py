from datetime import date

import pytest
from django.utils import timezone

from core.models import (
    Code,
    CodeEdition,
    CorpusCurrency,
    Regulation,
    SearchHistory,
    User,
)


@pytest.mark.django_db
class TestSearchHistory:
    def setup_method(self):
        self.user = User.objects.create_user(
            email="history@example.com",
            password="password",
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


@pytest.mark.django_db
class TestCorpusCurrency:
    def test_open_edition_among_closed_reports_present(self):
        """An open-ended current edition alongside older closed editions must
        report the corpus as still in force.

        ``Max(ineffective_date)`` ignores the current edition's NULL end date,
        so without an explicit open-edition check the masthead would fall back
        to the older edition's end date and wrongly mark the corpus closed.
        """
        code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
        old_edition = CodeEdition.objects.create(
            code=code, edition_id="2012", year=2012,
            effective_date=date(2012, 1, 1),
            ineffective_date=date(2024, 1, 1),
        )
        current_edition = CodeEdition.objects.create(
            code=code, edition_id="2024", year=2024,
            effective_date=date(2024, 1, 1),
            ineffective_date=None,
        )
        for edition in (old_edition, current_edition):
            Regulation.objects.create(
                reg_id=f"{edition.edition_id}/base", edition=edition, role="base",
                effective_date=edition.effective_date,
            )

        currency = CorpusCurrency.refresh()

        assert currency.corpus_span.endswith("present")
        assert currency.coverage_end is None or currency.coverage_end >= date(2024, 1, 1)
        assert currency.data_current_to is not None
