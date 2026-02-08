from unittest.mock import MagicMock, patch

import pytest

from api.llm_parser import parse_user_query


@pytest.mark.django_db
def test_parse_user_query_valid():
    """Test parsing a valid query."""
    with patch('anthropic.Anthropic') as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_response = MagicMock()

        # Simulate tool use response
        mock_tool_use = MagicMock()
        mock_tool_use.type = 'tool_use'
        mock_tool_use.input = {
            'date': '1993-01-01',
            'keywords': ['fire', 'safety'],
            'province': 'ON'
        }
        mock_response.content = [mock_tool_use]
        mock_client.messages.create.return_value = mock_response

        result = parse_user_query("Fire safety in Ontario 1993")

        assert result['date'] == '1993-01-01'
        assert 'fire' in result['keywords']
        assert result['province'] == 'ON'

@pytest.mark.django_db
def test_parse_user_query_invalid_keywords():
    """Test validation of keywords."""
    with patch('anthropic.Anthropic') as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_response = MagicMock()

        mock_tool_use = MagicMock()
        mock_tool_use.type = 'tool_use'
        mock_tool_use.input = {
            'date': '2020-01-01',
            'keywords': ['unknown_very_weird_keyword'],
            'province': 'ON'
        }
        mock_response.content = [mock_tool_use]
        mock_client.messages.create.return_value = mock_response

        with pytest.raises(ValueError) as excinfo:
            parse_user_query("Something weird")

        assert "Query does not contain recognized building code keywords" in str(excinfo.value)
