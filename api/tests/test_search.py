from datetime import date
from unittest.mock import patch

import pytest

from api.search import execute_search


@pytest.fixture
def mock_search_deps():
    with patch('api.search.mcp_server') as mock_mcp, \
         patch('api.search.get_applicable_codes') as mock_codes:
        mock_codes.return_value = ['NBC_2020', 'OBC_2024']
        yield mock_mcp, mock_codes


def test_execute_search_basic(mock_search_deps):
    """Test search resolution with mocked dependencies."""
    mock_mcp, mock_codes = mock_search_deps
    mock_mcp.search_code.return_value = {
        'results': [
            {
                'id': '3.1.1.1',
                'title': 'Fire Safety',
                'page': 50,
                'page_end': 52,
                'score': 1.0,
            }
        ]
    }

    params = {
        'date': '2024-01-01',
        'keywords': ['fire'],
        'province': 'ON'
    }

    response = execute_search(params)

    assert 'OBC_2024' in response['applicable_codes']
    assert len(response['results']) > 0
    assert response['results'][0]['id'] == '3.1.1.1'
    # Verify we called search with verbose=True and the base code
    mock_mcp.search_code.assert_any_call(
        query="fire",
        code="NBC",
        limit=10,
        verbose=True,
    )


def test_execute_search_doors_fire_safety(mock_search_deps):
    """Test that a realistic query for doors/fire/safety in ON finds results."""
    mock_mcp, mock_codes = mock_search_deps
    mock_codes.return_value = ['OBC_2024', 'NBC_2025']
    mock_mcp.search_code.return_value = {
        'results': [
            {
                'id': '3.1.8.1',
                'title': 'Fire Separations',
                'page': 120,
                'page_end': 125,
                'score': 0.9,
            },
            {
                'id': '3.1.8.5',
                'title': 'Fire-Rated Doors',
                'page': 125,
                'page_end': 128,
                'score': 0.85,
            },
        ]
    }

    params = {
        'date': '2026-02-05',
        'keywords': ['doors', 'fire', 'safety'],
        'province': 'ON',
    }

    response = execute_search(params)

    assert response['result_count'] > 0
    assert len(response['results']) > 0
    assert 'OBC_2024' in response['applicable_codes']
    assert 'NBC_2025' in response['applicable_codes']
    # Verify MCP was called for both code systems with verbose=True
    mock_mcp.search_code.assert_any_call(
        query='doors fire safety', code='OBC', limit=10, verbose=True
    )
    mock_mcp.search_code.assert_any_call(
        query='doors fire safety', code='NBC', limit=10, verbose=True
    )


def test_get_applicable_codes_ontario_2026():
    """Test that ON province correctly resolves to OBC and NBC codes."""
    from config.code_metadata import get_applicable_codes

    codes = get_applicable_codes('ON', date(2026, 2, 5))

    assert 'OBC_2024' in codes
    assert 'NBC_2025' in codes


def test_execute_search_no_codes():
    """Test when no codes are found for the date."""
    params = {
        'date': '1950-01-01',
        'keywords': ['fire'],
        'province': 'ON'
    }

    response = execute_search(params)
    assert 'error' in response
    assert response['results'] == []
