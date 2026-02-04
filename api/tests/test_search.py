import pytest
from datetime import date
from unittest.mock import MagicMock, patch
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
            {'id': '3.1.1.1', 'title': 'Fire Safety', 'page': 50, 'score': 1.0}
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
    # Verify we called search with the base code
    mock_mcp.search_code.assert_any_call(
        query="fire",
        code="NBC",
        limit=10
    )

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
