from datetime import date as real_date
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from api.llm_parser import (
    _as_table_ref,
    extract_section_references,
    extract_table_references,
    parse_user_query,
    strip_table_references,
)
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


class TestTableReferenceExtraction:
    """Regex pre-extraction of table references (no LLM, no DB)."""

    def test_appendix_letter_table(self):
        # The case that returned nothing before: appendix tables are
        # letter-numbered with no dotted core, invisible to SECTION_REF_RE.
        assert extract_table_references("Table A-1 in the year 2000") == ["Table A-1"]

    def test_dotted_space_form_is_a_table_not_a_provision(self):
        # "Table 9.10.14.1" (space, no hyphen) must read as one table reference,
        # not degrade to a bare "9.10.14.1" provision id.
        q = "fire safety Table 9.10.14.1 for a house"
        assert extract_table_references(q) == ["Table 9.10.14.1"]
        assert extract_section_references(strip_table_references(q)) == []

    def test_hyphenated_appendix(self):
        assert extract_table_references("Table-A-12") == ["Table-A-12"]

    def test_plain_provision_is_not_a_table(self):
        assert extract_table_references("section 9.10.14.1 only") == []


def test_as_table_ref_prefixes_bare_ids_only():
    # A bare id the LLM might return gets the marker the engine routes on;
    # an already-prefixed reference passes through unchanged.
    assert _as_table_ref("A-1") == "Table-A-1"
    assert _as_table_ref("9.10.14.1") == "Table-9.10.14.1"
    assert _as_table_ref("Table A-1") == "Table A-1"
    assert _as_table_ref("table-a-12") == "table-a-12"


@pytest.mark.django_db
@override_settings(ANTHROPIC_API_KEY="test-key")
def test_table_only_query_resolves_via_regex_without_llm():
    """A query that is purely a table reference short-circuits the API."""
    with patch("anthropic.Anthropic") as mock_anthropic:
        result = parse_user_query("Table A-1")
        assert result["section_references"] == ["Table A-1"]
        mock_anthropic.return_value.messages.create.assert_not_called()


@pytest.mark.django_db
@override_settings(ANTHROPIC_API_KEY="test-key")
def test_llm_table_reference_folded_into_section_references():
    """A table the regex can't see but the LLM names joins the ref channel, and
    a keyword-less table query is not rejected for lacking keywords."""
    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        block = MagicMock()
        block.type = "tool_use"
        block.input = {
            "date": "2000-01-01",
            "keywords": [],
            "province": "ON",
            "table_references": ["Table A-1"],
        }
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response

        result = parse_user_query("the appendix climate table for 2000")

        assert result["section_references"] == ["Table A-1"]
        # The raw tool field is flattened away — downstream reads one channel.
        assert "table_references" not in result


@pytest.mark.django_db
@override_settings(ANTHROPIC_API_KEY="test-key")
def test_llm_table_reference_survives_cache_hit():
    """On a cache hit the LLM-extracted table ref must be preserved, not
    overwritten by the (empty) regex re-extraction of the same query."""
    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = mock_anthropic.return_value
        block = MagicMock()
        block.type = "tool_use"
        block.input = {
            "date": "2000-01-01",
            "keywords": [],
            "province": "ON",
            "table_references": ["Table A-1"],
        }
        response = MagicMock()
        response.content = [block]
        mock_client.messages.create.return_value = response

        query = "the appendix climate table for 2000"
        r1 = parse_user_query(query)
        assert r1["section_references"] == ["Table A-1"]
        assert mock_client.messages.create.call_count == 1

        # Identical query -> cache hit, no new API call, ref still present.
        r2 = parse_user_query(query)
        assert r2["section_references"] == ["Table A-1"]
        assert mock_client.messages.create.call_count == 1
