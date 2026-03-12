"""
Integration tests that exercise the search pipeline against real DB records.

These tests create their own CodeSystem/CodeEdition/CodeMap/CodeMapNode
records and call the actual search functions — only the LLM parser is mocked.

Run:  pytest api/tests/test_integration.py -v
Skip: pytest -m "not integration"
"""

from datetime import date
from unittest.mock import patch

import pytest

from api.formatters import format_search_results
from api.search.orchestration import execute_search
from core.models import (
    CodeEdition,
    CodeMap,
    CodeMapNode,
    CodeSystem,
    ProvinceCodeMap,
    SearchHistory,
)
from services.search_service import run_search


def _create_obc_fixtures():
    """Create a minimal OBC code system with e-Laws nodes (html, no page)."""
    system = CodeSystem.objects.create(
        code="OBC", display_name="Ontario Building Code", is_national=False
    )
    ProvinceCodeMap.objects.create(province="ON", code_system=system)
    edition = CodeEdition.objects.create(
        system=system,
        edition_id="2024",
        year=2024,
        map_codes=["OBC_2024"],
        effective_date=date(2024, 1, 1),
        source="e-Laws",
        source_url="https://www.ontario.ca/laws/regulation/120332",
    )
    code_map = CodeMap.objects.create(code_name="OBC_2024", map_code="OBC_2024")
    CodeMapNode.objects.create(
        code_map=code_map,
        node_id="B-3.2.7.1.",
        title="Fire Separations in Buildings Used for Major Occupancies",
        html="<p>Every <em>building</em> shall have <strong>fire separations</strong>…</p>",
        keywords=["fire", "separations", "major", "occupancy"],
        parent_id="B-3.2.7.",
    )
    CodeMapNode.objects.create(
        code_map=code_map,
        node_id="B-3.2.7.2.",
        title="Minimum Fire-Resistance Rating",
        html="<p>The minimum fire-resistance rating required…</p>",
        keywords=["fire", "resistance", "rating"],
        parent_id="B-3.2.7.",
    )
    return system, edition, code_map


def _create_nbc_fixtures():
    """Create a minimal NBC code system with PDF-sourced nodes (page, bbox, no html)."""
    system = CodeSystem.objects.create(
        code="NBC", display_name="National Building Code", is_national=True
    )
    edition = CodeEdition.objects.create(
        system=system,
        edition_id="2025",
        year=2025,
        map_codes=["NBC"],
        effective_date=date(2025, 3, 21),
        pdf_files={"NBC": "NBC2025p1.pdf"},
        download_url="https://nrc-publications.canada.ca/nbc2025",
    )
    code_map = CodeMap.objects.create(code_name="NBC_2025", map_code="NBC")
    CodeMapNode.objects.create(
        code_map=code_map,
        node_id="B-9.10.14.1.",
        title="Application",
        page=710,
        page_end=710,
        initial_page_top=112.5,
        final_page_bottom=305.2,
        keywords=["application", "housing", "small", "buildings"],
        parent_id="B-9.10.14.",
    )
    return system, edition, code_map


@pytest.mark.integration
@pytest.mark.django_db
class TestOBCSearchWithHTML:
    def test_search_returns_obc_results_with_html(self):
        _create_obc_fixtures()

        result = execute_search(
            {"date": "2024-06-01", "keywords": ["fire", "separations"], "province": "ON"}
        )

        assert result["result_count"] > 0
        matched = [r for r in result["results"] if r["id"] == "B-3.2.7.1."]
        assert len(matched) == 1
        assert matched[0]["html_content"] is not None
        assert "fire separations" in matched[0]["html_content"].lower()

    def test_formatted_results_include_source_url(self):
        _create_obc_fixtures()

        raw_result = execute_search(
            {"date": "2024-06-01", "keywords": ["fire"], "province": "ON"}
        )
        formatted = format_search_results(raw_result["results"])

        obc_results = [r for r in formatted if r.get("code") == "OBC_2024"]
        assert obc_results
        for r in obc_results:
            assert r["source_url"]


@pytest.mark.integration
@pytest.mark.django_db
class TestNBCSearchWithPageBounds:
    def test_search_returns_page_bounds(self):
        _create_nbc_fixtures()

        result = execute_search(
            {"date": "2025-06-01", "keywords": ["application", "housing"], "province": "ON"}
        )

        nbc_results = [r for r in result["results"] if r.get("code_edition") == "NBC_2025"]
        assert nbc_results
        node = nbc_results[0]
        assert node["initial_page_top"] == pytest.approx(112.5)
        assert node["final_page_bottom"] == pytest.approx(305.2)
        assert node["page"] == 710

    def test_formatted_results_include_pdf_filename(self):
        _create_nbc_fixtures()

        raw_result = execute_search(
            {"date": "2025-06-01", "keywords": ["application"], "province": "ON"}
        )
        formatted = format_search_results(raw_result["results"])

        nbc_results = [r for r in formatted if r.get("code") == "NBC_2025"]
        assert nbc_results
        assert nbc_results[0]["pdf_filename"] == "NBC2025p1.pdf"


@pytest.mark.integration
@pytest.mark.django_db
class TestRunSearchEndToEnd:
    @patch("services.search_service.parse_user_query")
    def test_run_search_with_mocked_llm(self, mock_parse):
        _create_obc_fixtures()
        mock_parse.return_value = {
            "date": "2024-06-01",
            "province": "ON",
            "keywords": ["fire"],
            "section_references": [],
        }

        result = run_search("What are the fire separation requirements?")

        assert result["success"] is True
        assert len(result["results"]) > 0
        assert result["error"] is None
        assert SearchHistory.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
class TestTransitionContextInOverlapWindow:
    def test_transition_context_present(self):
        # Create BCBC 2018 (old) and 2024 (new) editions
        system = CodeSystem.objects.create(
            code="BCBC", display_name="BC Building Code", is_national=False
        )
        ProvinceCodeMap.objects.create(province="BC", code_system=system)

        CodeEdition.objects.create(
            system=system,
            edition_id="2018",
            year=2018,
            map_codes=["BCBC_2018"],
            effective_date=date(2018, 12, 10),
            superseded_date=date(2025, 3, 10),
        )
        CodeEdition.objects.create(
            system=system,
            edition_id="2024",
            year=2024,
            map_codes=["BCBC_2024"],
            effective_date=date(2024, 3, 8),
        )

        old_map = CodeMap.objects.create(code_name="BCBC_2018", map_code="BCBC_2018")
        new_map = CodeMap.objects.create(code_name="BCBC_2024", map_code="BCBC_2024")

        for code_map in (old_map, new_map):
            CodeMapNode.objects.create(
                code_map=code_map,
                node_id="B-3.2.9.",
                title="Fire Separations",
                keywords=["fire", "separations"],
                parent_id="B-3.2.",
            )

        # Search during overlap window (2024-03-08 to 2025-03-09)
        result = execute_search(
            {"date": "2024-06-01", "keywords": ["fire", "separations"], "province": "BC"}
        )

        matched = [r for r in result["results"] if r["id"] == "B-3.2.9."]
        assert len(matched) == 2

        editions = {r["code_edition"] for r in matched}
        assert editions == {"BCBC_2024", "BCBC_2018"}

        with_context = [r for r in matched if r.get("transition_context")]
        assert len(with_context) == 2

        primary = [r for r in with_context if r["transition_context"]["is_primary"]]
        assert primary[0]["code_edition"] == "BCBC_2024"


@pytest.mark.integration
@pytest.mark.django_db
class TestSectionReferenceSearch:
    def test_section_ref_match(self):
        _create_obc_fixtures()

        result = execute_search(
            {
                "date": "2024-06-01",
                "keywords": [],
                "province": "ON",
                "section_references": ["3.2.7.1"],
            }
        )

        matched = [r for r in result["results"] if r["id"] == "B-3.2.7.1."]
        assert len(matched) == 1
        assert matched[0]["score"] >= 2.0
