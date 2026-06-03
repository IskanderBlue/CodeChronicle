from datetime import date

import pytest

from api.search.orchestration import execute_search
from core.models import (
    Code,
    CodeEdition,
    CodeEditionProvision,
    CodeEditionProvisionVersion,
    ProvinceCode,
)


@pytest.fixture
def obc_setup(db):
    """Create a minimal OBC code system with one edition and provisions."""
    code = Code.objects.create(code="OBC", display_name="Ontario Building Code")
    ProvinceCode.objects.create(province="ON", code=code)

    edition = CodeEdition.objects.create(
        code=code,
        edition_id="2024",
        year=2024,
        effective_date=date(2024, 1, 1),
    )

    parent_prov = CodeEditionProvision.objects.create(
        edition=edition,
        provision_id="3.2",
        level=CodeEditionProvision.Level.SECTION,
        division="B",
    )
    child_prov = CodeEditionProvision.objects.create(
        edition=edition,
        provision_id="3.2.9",
        level=CodeEditionProvision.Level.SUBSECTION,
        division="B",
        parent=parent_prov,
    )

    parent_version = CodeEditionProvisionVersion.objects.create(
        provision=parent_prov,
        version=0,
        effective_date=date(2024, 1, 1),
        title="Fire Safety",
        html="<p>Fire safety requirements.</p>",
        keyword_counts={"fire": 5, "safety": 3},
    )
    child_version = CodeEditionProvisionVersion.objects.create(
        provision=child_prov,
        version=0,
        effective_date=date(2024, 1, 1),
        title="Fire Separations",
        html="<p>Fire separation requirements for buildings.</p>",
        keyword_counts={"fire": 4, "separation": 6, "building": 2},
    )

    return {
        "code": code,
        "edition": edition,
        "parent_prov": parent_prov,
        "child_prov": child_prov,
        "parent_version": parent_version,
        "child_version": child_version,
    }


@pytest.mark.django_db
class TestExecuteSearchKeywords:
    def test_keyword_query_returns_matching_provisions(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        assert response["result_count"] > 0
        ids = [r["id"] for r in response["results"]]
        # Both provisions have "fire" in keyword_counts
        assert "3.2" in ids or "3.2.9" in ids

    def test_keyword_query_returns_scored_results(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["separation"],
            "province": "ON",
        })

        assert response["result_count"] >= 1
        # The child provision has "separation" as a keyword
        matching = [r for r in response["results"] if r["id"] == "3.2.9"]
        assert len(matching) == 1
        assert matching[0]["score"] > 0

    def test_no_results_when_keywords_dont_match(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["plumbing"],
            "province": "ON",
        })

        assert response["result_count"] == 0
        assert response["results"] == []

    def test_no_results_when_no_keywords_or_references(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": [],
            "province": "ON",
        })

        assert response["result_count"] == 0
        assert response["results"] == []

    def test_results_include_code_edition_field(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        for result in response["results"]:
            assert result["code_edition"] == "OBC_2024"

    def test_results_include_applicable_codes(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        assert "OBC_2024" in response["applicable_codes"]

    def test_results_include_top_results_metadata(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        assert len(response["top_results_metadata"]) > 0
        meta = response["top_results_metadata"][0]
        assert "code" in meta
        assert "section_id" in meta
        assert "title" in meta


@pytest.mark.django_db
class TestExecuteSearchProvisionReferences:
    def test_provision_reference_matches_by_id(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": [],
            "section_references": ["3.2.9"],
            "province": "ON",
        })

        assert response["result_count"] >= 1
        ids = [r["id"] for r in response["results"]]
        assert "3.2.9" in ids

    def test_provision_reference_partial_match(self, obc_setup):
        response = execute_search({
            "date": "2024-06-01",
            "keywords": [],
            "section_references": ["3.2"],
            "province": "ON",
        })

        # "3.2" appears in both "3.2" and "3.2.9" provision_ids
        assert response["result_count"] >= 1


@pytest.mark.django_db
class TestExecuteSearchTransitions:
    def test_overlapping_versions_grouped_as_transition(self, db):
        """Two versions of the same provision with overlapping dates get transition_context."""
        code = Code.objects.create(code="BCBC", display_name="BC Building Code")
        ProvinceCode.objects.create(province="BC", code=code)

        edition = CodeEdition.objects.create(
            code=code,
            edition_id="2024",
            year=2024,
            effective_date=date(2024, 1, 1),
        )

        provision = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id="3.2.9",
            level=CodeEditionProvision.Level.SUBSECTION,
            division="B",
            version_count=2,
        )

        # Version 0: old version, in force until mid-2025 (grace period)
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(2024, 1, 1),
            ineffective_date=date(2025, 6, 1),
            title="Fire Separations (old)",
            html="<p>Old fire separation requirements.</p>",
            keyword_counts={"fire": 4, "separation": 5},
        )

        # Version 1: new version, effective from mid-2024 (overlaps with v0)
        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=1,
            effective_date=date(2024, 6, 1),
            ineffective_date=None,
            title="Fire Separations (new)",
            html="<p>New fire separation standards.</p>",
            keyword_counts={"fire": 4, "separation": 5},
        )

        # Search during overlap period
        response = execute_search({
            "date": "2024-09-01",
            "keywords": ["fire"],
            "province": "BC",
        })

        fire_results = [r for r in response["results"] if r["id"] == "3.2.9"]
        assert len(fire_results) == 2

        # Both should have transition_context
        contexts = [r.get("transition_context") for r in fire_results]
        assert all(ctx is not None for ctx in contexts)
        primary_count = sum(1 for ctx in contexts if ctx.get("is_primary"))
        assert primary_count == 1

    def test_no_transition_when_single_version_in_force(self, obc_setup):
        """A single in-force version should not have transition_context."""
        response = execute_search({
            "date": "2024-06-01",
            "keywords": ["fire"],
            "province": "ON",
        })

        for result in response["results"]:
            assert result.get("transition_context") is None


@pytest.mark.django_db
class TestExecuteSearchDateFiltering:
    def test_version_not_yet_effective_excluded(self, db):
        """Versions with effective_date after search_date should not appear."""
        code = Code.objects.create(code="NBC", display_name="National Building Code")
        ProvinceCode.objects.create(province="AB", code=code)

        edition = CodeEdition.objects.create(
            code=code,
            edition_id="2025",
            year=2025,
            effective_date=date(2025, 1, 1),
        )

        provision = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id="5.1",
            level=CodeEditionProvision.Level.SECTION,
            division="B",
        )

        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(2025, 6, 1),
            title="Future provision",
            keyword_counts={"fire": 3},
        )

        response = execute_search({
            "date": "2025-01-15",
            "keywords": ["fire"],
            "province": "AB",
        })

        assert response["result_count"] == 0

    def test_ineffective_version_excluded(self, db):
        """Versions whose ineffective_date has passed should not appear."""
        code = Code.objects.create(code="NBC", display_name="National Building Code")
        ProvinceCode.objects.create(province="AB", code=code)

        edition = CodeEdition.objects.create(
            code=code,
            edition_id="2020",
            year=2020,
            effective_date=date(2020, 1, 1),
        )

        provision = CodeEditionProvision.objects.create(
            edition=edition,
            provision_id="5.1",
            level=CodeEditionProvision.Level.SECTION,
            division="B",
        )

        CodeEditionProvisionVersion.objects.create(
            provision=provision,
            version=0,
            effective_date=date(2020, 1, 1),
            ineffective_date=date(2023, 1, 1),
            title="Old provision",
            keyword_counts={"fire": 3},
        )

        response = execute_search({
            "date": "2024-01-01",
            "keywords": ["fire"],
            "province": "AB",
        })

        assert response["result_count"] == 0
