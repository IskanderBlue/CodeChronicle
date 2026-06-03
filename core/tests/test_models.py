from datetime import date

import pytest
from django.utils import timezone

from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    CodeEditionProvisionVersionClause,
    CorpusCurrency,
    Regulation,
    RegulationClause,
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


@pytest.mark.django_db
class TestContributingClauseOrdering:
    """first/last_contributing_clause follow the (filed_date, clause_id)
    contract order via the through model's apply_order — not heap order."""

    def _version_with_two_clauses(self) -> CodeEditionProvisionVersion:
        code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
        edition = CodeEdition.objects.create(
            code=code, edition_id="1997", year=1997,
            effective_date=date(1998, 4, 6),
        )
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id="3.1.4.7.", level="article", division="B",
        )
        version = CodeEditionProvisionVersion.objects.create(
            provision=provision, version=2,
            effective_date=date(1999, 4, 1), title="Fire Separations",
        )
        # Two amending regs filed on different dates, created in the *reverse*
        # of filed order so heap/pk order would disagree with the contract
        # (regulation.filed_date, clause_id) order.
        later = Regulation.objects.create(
            reg_id="152/99", edition=edition, role="amendment",
            effective_date=date(1999, 4, 1), filed_date=date(1999, 3, 15),
        )
        earlier = Regulation.objects.create(
            reg_id="22/98", edition=edition, role="amendment",
            effective_date=date(1998, 4, 6), filed_date=date(1998, 2, 1),
        )
        self.cl_later = RegulationClause.objects.create(
            regulation=later, clause_id="1.(1)",
        )
        self.cl_earlier = RegulationClause.objects.create(
            regulation=earlier, clause_id="3.(2)",
        )
        # apply_order mirrors the (filed_date, clause_id) projection load_edition
        # writes: earliest-filed reg first.
        CodeEditionProvisionVersionClause.objects.create(
            version=version, clause=self.cl_earlier, apply_order=0,
        )
        CodeEditionProvisionVersionClause.objects.create(
            version=version, clause=self.cl_later, apply_order=1,
        )
        return version

    def test_first_is_earliest_filed_last_is_latest(self):
        version = self._version_with_two_clauses()
        assert version.first_contributing_clause == self.cl_earlier
        assert version.last_contributing_clause == self.cl_later

    def test_empty_when_no_contributing_clauses(self):
        code = Code.objects.create(code="NBC", display_name="National Building Code")
        edition = CodeEdition.objects.create(
            code=code, edition_id="2020", year=2020, effective_date=date(2020, 1, 1),
        )
        provision = CodeEditionProvision.objects.create(
            edition=edition, provision_id="1.1.", level="section", division="",
        )
        version = CodeEditionProvisionVersion.objects.create(
            provision=provision, version=0, effective_date=date(2020, 1, 1),
        )
        assert version.first_contributing_clause is None
        assert version.last_contributing_clause is None
