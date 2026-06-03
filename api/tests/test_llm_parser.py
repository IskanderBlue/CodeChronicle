from datetime import date as real_date
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from api.llm_parser import parse_user_query
from core.models import QueryCache


def _tool_use_response(date_str: str, keywords=("fire",)):
    response = MagicMock()
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"date": date_str, "keywords": list(keywords), "province": "ON"}
    response.content = [block]
    return response


@pytest.mark.django_db
@override_settings(ANTHROPIC_API_KEY="test-key")
def test_parse_user_query_valid():
    """Test parsing a valid query."""
    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_response = MagicMock()

        # Simulate tool use response
        mock_tool_use = MagicMock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.input = {
            "date": "1993-01-01",
            "keywords": ["fire", "safety"],
            "province": "ON",
        }
        mock_response.content = [mock_tool_use]
        mock_client.messages.create.return_value = mock_response

        result = parse_user_query("Fire safety in Ontario 1993")

        assert result["date"] == "1993-01-01"
        assert "fire" in result["keywords"]
        assert result["province"] == "ON"


@pytest.mark.django_db
@override_settings(ANTHROPIC_API_KEY="test-key")
def test_parse_user_query_invalid_keywords():
    """Test validation of keywords."""
    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        mock_response = MagicMock()

        mock_tool_use = MagicMock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.input = {
            "date": "2020-01-01",
            "keywords": ["unknown_very_weird_keyword"],
            "province": "ON",
        }
        mock_response.content = [mock_tool_use]
        mock_client.messages.create.return_value = mock_response

        with pytest.raises(ValueError) as excinfo:
            parse_user_query("Something weird")

        assert "Query does not contain recognized building code keywords" in str(excinfo.value)


@pytest.mark.django_db
@override_settings(ANTHROPIC_API_KEY="test-key")
def test_measurement_year_does_not_freeze_cache():
    """Regression for the _DATE_LIKE_RE cache-freeze bug.

    "1900 mm" reads as a date to a 4-digit-year regex, but the LLM correctly
    falls back to *today*. The parse must therefore be marked relative and
    re-run once the day rolls — not frozen forever serving a stale today-date.
    """
    query = "minimum 1900 mm clearance for fire"
    with patch("anthropic.Anthropic") as mock_anthropic, \
            patch("api.llm_parser.date") as mock_date:
        mock_client = mock_anthropic.return_value

        # Day 1: no real date in the query, so the LLM defaults to today.
        mock_date.today.return_value = real_date(2026, 6, 3)
        mock_client.messages.create.return_value = _tool_use_response("2026-06-03")
        r1 = parse_user_query(query)
        assert r1["date"] == "2026-06-03"
        assert mock_client.messages.create.call_count == 1
        assert QueryCache.objects.get().date_is_relative is True

        # Same day, same query -> cache hit, no second API call.
        parse_user_query(query)
        assert mock_client.messages.create.call_count == 1

        # The day rolls: the relative parse is stale, so we re-parse and get
        # the new today's date instead of the frozen 2026-06-03.
        mock_date.today.return_value = real_date(2026, 6, 4)
        mock_client.messages.create.return_value = _tool_use_response("2026-06-04")
        r3 = parse_user_query(query)
        assert r3["date"] == "2026-06-04"
        assert mock_client.messages.create.call_count == 2


@pytest.mark.django_db
@override_settings(ANTHROPIC_API_KEY="test-key")
def test_explicit_date_parse_is_stable_across_days():
    """A query with a real construction year caches indefinitely — its parse
    doesn't depend on today, so a day roll must not trigger a re-parse."""
    query = "fire safety for a house built in 1995"
    with patch("anthropic.Anthropic") as mock_anthropic, \
            patch("api.llm_parser.date") as mock_date:
        mock_client = mock_anthropic.return_value

        mock_date.today.return_value = real_date(2026, 6, 3)
        mock_client.messages.create.return_value = _tool_use_response("1995-01-01")
        r1 = parse_user_query(query)
        assert r1["date"] == "1995-01-01"
        assert QueryCache.objects.get().date_is_relative is False
        assert mock_client.messages.create.call_count == 1

        # A later day: still a cache hit, no new API call.
        mock_date.today.return_value = real_date(2027, 1, 1)
        r2 = parse_user_query(query)
        assert r2["date"] == "1995-01-01"
        assert mock_client.messages.create.call_count == 1
