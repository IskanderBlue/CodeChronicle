"""Tests for TF-IDF keyword scoring in the search engine."""

from unittest.mock import patch

import pytest

from api.search import execute_search
from api.search.engine import _search_code_db, _tf
from core.models import CodeMap, CodeMapNode


@pytest.fixture
def mock_search_deps(db):
    with (
        patch("api.search.orchestration.get_applicable_codes") as mock_codes,
        patch("api.search.orchestration.get_map_codes") as mock_map_codes,
    ):
        mock_codes.return_value = ["OBC_2024"]
        mock_map_codes.side_effect = lambda code_name: {
            "OBC_2024": ["OBC_Vol1"],
        }.get(code_name, [])
        yield mock_codes


def test_tf_log_normalization():
    """TF function should use log-normalized term frequency."""
    counts = {"fire": 1, "sprinkler": 8, "building": 10}
    assert _tf("fire", counts) == pytest.approx(1.0)  # 1 + log(1) = 1.0
    assert _tf("sprinkler", counts) > _tf("fire", counts)  # log(8) > log(1)
    assert _tf("missing", counts) == 0.0


def test_tf_zero_for_missing_term():
    """TF returns 0 for terms not in the counts dict."""
    assert _tf("absent", {"fire": 5}) == 0.0
    assert _tf("anything", {}) == 0.0


@pytest.mark.django_db
def test_tfidf_ranks_rare_repeated_term_higher(mock_search_deps):
    """A section mentioning a rare term many times should rank higher."""
    obc_map = CodeMap.objects.create(code_name="OBC_2024", map_code="OBC_Vol1")

    # Section A: mentions "fire" once, "building" many times
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id="3.1.1.1",
        title="General Building",
        page=10,
        page_end=12,
        keyword_counts={"fire": 1, "building": 10},
    )
    # Section B: mentions "fire" many times, "sprinkler" present
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id="3.1.8.5",
        title="Fire Sprinkler Systems",
        page=125,
        page_end=128,
        keyword_counts={"fire": 8, "sprinkler": 3},
    )

    result = _search_code_db("fire sprinkler", "OBC_Vol1", limit=10)
    assert len(result["results"]) == 2
    # Section B should rank higher: it has more "fire" mentions and "sprinkler"
    assert result["results"][0]["id"] == "3.1.8.5"
    assert result["results"][1]["id"] == "3.1.1.1"


@pytest.mark.django_db
def test_tfidf_fallback_when_no_idf_data(mock_search_deps):
    """Search should work gracefully when the matview doesn't exist or is empty."""
    obc_map = CodeMap.objects.create(code_name="OBC_2024", map_code="OBC_Vol1")
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id="3.1.1.1",
        title="Fire Safety",
        page=10,
        page_end=12,
        keyword_counts={"fire": 1, "safety": 1},
    )

    # Even with no matview data, search should still find results
    result = _search_code_db("fire safety", "OBC_Vol1", limit=10)
    assert len(result["results"]) == 1
    assert result["results"][0]["id"] == "3.1.1.1"
    assert result["results"][0]["score"] > 0


@pytest.mark.django_db
def test_keyword_counts_loaded_in_search(mock_search_deps):
    """execute_search should work with keyword_counts field."""
    obc_map = CodeMap.objects.create(code_name="OBC_2024", map_code="OBC_Vol1")
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id="3.1.8.1",
        title="Fire Separations",
        page=120,
        page_end=125,
        keyword_counts={"fire": 2, "separations": 1},
    )

    params = {"date": "2026-01-01", "keywords": ["fire"], "province": "ON"}
    response = execute_search(params)
    assert response["result_count"] > 0


@pytest.mark.django_db
def test_suggest_similar_keywords_uses_keyword_counts(mock_search_deps):
    """Keyword suggestions should draw from keyword_counts keys."""
    from api.search.engine import _suggest_similar_keywords

    obc_map = CodeMap.objects.create(code_name="OBC_2024", map_code="OBC_Vol1")
    CodeMapNode.objects.create(
        code_map=obc_map,
        node_id="3.1.1.1",
        title="Fire Safety",
        page=10,
        page_end=12,
        keyword_counts={"fire": 3, "sprinkler": 2, "safety": 1},
    )

    suggestions = _suggest_similar_keywords("fir", "OBC_Vol1")
    assert "fire" in suggestions


@pytest.mark.django_db
def test_load_maps_keyword_counts_from_json(tmp_path):
    """load_maps should load keyword_counts from map JSON."""
    import json

    from django.core.management import call_command

    payload = {
        "code_name": "TEST_2024",
        "sections": [
            {
                "id": "1.1.1.1",
                "title": "Test Section",
                "page": 1,
                "page_end": 2,
                "keyword_counts": {"fire": 3, "safety": 1},
            },
        ],
    }

    map_path = tmp_path / "TEST_Vol1.json"
    map_path.write_text(json.dumps(payload), encoding="utf-8")

    call_command("load_maps", source=str(tmp_path))

    node = CodeMapNode.objects.get(node_id="1.1.1.1")
    assert node.keyword_counts == {"fire": 3, "safety": 1}
