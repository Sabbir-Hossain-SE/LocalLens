"""
Tests for the intent parser module.

Covers 12 diverse query patterns to validate that the regex fallback
correctly extracts category, location, count, sort_by, and filters.

These tests run entirely against the regex fallback so they work without
a running Ollama or Groq instance.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the backend root is on the path when running tests directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.intent_parser import IntentParser, _regex_fallback
from app.models.intent import ParsedIntent


# ---------------------------------------------------------------------------
# Regex-fallback unit tests
# ---------------------------------------------------------------------------

class TestRegexFallback:
    """Unit tests for the _regex_fallback function."""

    def test_sushi_near_me(self):
        """Basic 'near me' query should extract sushi category and near_me location."""
        intent = _regex_fallback("best sushi restaurants near me")
        assert "sushi" in intent.category.lower()
        assert intent.location == "near_me"
        assert intent.count == 5  # default

    def test_top_n_count_extraction(self):
        """Explicit count in query should be extracted."""
        intent = _regex_fallback("top 10 coffee shops in Seattle")
        assert intent.count == 10

    def test_city_location_extraction(self):
        """City name in 'in <city>' pattern should be captured."""
        intent = _regex_fallback("top 3 gyms in Austin TX")
        assert "austin" in intent.location.lower()
        assert intent.count == 3

    def test_open_now_filter(self):
        """'open now' phrase should set filters.open_now = True."""
        intent = _regex_fallback("dentist open now within 3 km")
        assert intent.filters.open_now is True
        assert "dentist" in intent.category.lower()

    def test_radius_km_extraction(self):
        """'within X km' should populate radius_km."""
        intent = _regex_fallback("coffee shops within 2 km")
        assert abs(intent.radius_km - 2.0) < 0.1

    def test_radius_miles_conversion(self):
        """Radius in miles should be converted to km."""
        intent = _regex_fallback("yoga studios within 5 miles")
        # 5 miles ≈ 8.047 km
        assert 7.5 < intent.radius_km < 8.5

    def test_zip_code_as_location(self):
        """5-digit ZIP code should be captured as the location."""
        intent = _regex_fallback("cheap pizza in 11201")
        assert intent.location == "11201"

    def test_affordable_price_level(self):
        """Cheap / affordable keywords should set price_level = 'affordable'."""
        intent = _regex_fallback("cheap pizza places in Brooklyn")
        assert intent.filters.price_level == "affordable"

    def test_expensive_price_level(self):
        """Fancy / expensive keywords should set price_level = 'expensive'."""
        intent = _regex_fallback("fancy restaurants in Manhattan")
        assert intent.filters.price_level == "expensive"

    def test_sort_by_distance(self):
        """Nearest / closest keywords should set sort_by = 'distance'."""
        intent = _regex_fallback("nearest pharmacy to me")
        assert intent.sort_by == "distance"

    def test_hotel_category(self):
        """Hotel keyword should map to hotel category."""
        intent = _regex_fallback("hotels in San Francisco")
        assert "hotel" in intent.category.lower()
        assert "san francisco" in intent.location.lower()

    def test_nearby_synonym(self):
        """'nearby' is a synonym for 'near me'."""
        intent = _regex_fallback("grocery stores nearby open now")
        assert intent.location == "near_me"
        assert intent.filters.open_now is True

    def test_raw_query_preserved(self):
        """raw_query must match the original input."""
        query = "Best coffee near me open now"
        intent = _regex_fallback(query)
        assert intent.raw_query == query

    def test_confidence_lower_for_regex(self):
        """Regex fallback should report lower confidence than LLM (< 1.0)."""
        intent = _regex_fallback("sushi near me")
        assert intent.confidence < 1.0

    def test_pydantic_validation_passed(self):
        """The returned object must be a valid ParsedIntent (no validation errors)."""
        intent = _regex_fallback("best bars in Chicago")
        assert isinstance(intent, ParsedIntent)
        assert intent.count >= 1


# ---------------------------------------------------------------------------
# IntentParser integration tests (LLM mocked)
# ---------------------------------------------------------------------------

class TestIntentParserWithMockedLLM:
    """Integration tests for IntentParser with the LLM mocked out."""

    @pytest.mark.asyncio
    async def test_parse_uses_llm_when_available(self):
        """When LLM returns valid JSON, parse() should return high-confidence intent."""
        llm_response = json.dumps({
            "category": "sushi restaurant",
            "count": 5,
            "location": "near_me",
            "radius_km": 5.0,
            "sort_by": "rating",
            "filters": {"open_now": False, "min_rating": None, "price_level": None, "max_distance_km": None},
            "confidence": 0.95,
        })

        parser = IntentParser()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=llm_response)
        parser._llm = mock_llm

        intent = await parser.parse("best sushi near me")
        assert "sushi" in intent.category.lower()
        assert intent.confidence == 0.95

    @pytest.mark.asyncio
    async def test_parse_falls_back_to_regex_on_llm_failure(self):
        """When LLM raises an exception, parse() should fall back to regex."""
        parser = IntentParser()
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ConnectionRefusedError("Ollama not running")
        parser._llm = mock_llm

        intent = await parser.parse("dentist open now near me")
        assert "dentist" in intent.category.lower()
        assert intent.filters.open_now is True
        assert intent.confidence < 1.0  # Regex fallback lowers confidence

    @pytest.mark.asyncio
    async def test_parse_falls_back_on_invalid_json(self):
        """When LLM returns garbled text, parse() should fall back gracefully."""
        parser = IntentParser()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="I'm not JSON!")
        parser._llm = mock_llm

        intent = await parser.parse("coffee shops in Seattle")
        # Should still return something valid
        assert isinstance(intent, ParsedIntent)

    @pytest.mark.asyncio
    async def test_parse_no_llm_configured(self):
        """When LLM is not configured at all, regex fallback handles the query."""
        parser = IntentParser()
        parser._llm = None

        with patch.object(parser, "_init_llm", return_value=None):
            intent = await parser.parse("top 5 gyms in Austin TX")
        assert "gym" in intent.category.lower()


# ---------------------------------------------------------------------------
# Fixture-driven tests
# ---------------------------------------------------------------------------

class TestSampleQueryFixtures:
    """Load sample_queries.json and smoke-test the regex fallback against each."""

    @pytest.fixture(scope="class")
    def sample_queries(self):
        fixture_path = Path(__file__).parent / "fixtures" / "sample_queries.json"
        with open(fixture_path) as f:
            return json.load(f)

    def test_all_fixtures_parse_without_error(self, sample_queries):
        """Every fixture query should parse without raising an exception."""
        for item in sample_queries:
            intent = _regex_fallback(item["query"])
            assert isinstance(intent, ParsedIntent), f"Failed for query: {item['query']}"

    def test_near_me_queries_resolved(self, sample_queries):
        """Queries with near_me expectation should resolve to near_me."""
        near_me_cases = [i for i in sample_queries if i.get("expected_location") == "near_me"]
        assert len(near_me_cases) >= 1
        for item in near_me_cases:
            intent = _regex_fallback(item["query"])
            assert intent.location == "near_me", f"Expected near_me for: {item['query']}"

    def test_open_now_flag_detected(self, sample_queries):
        """Queries that expect open_now=True should have the flag set."""
        open_now_cases = [i for i in sample_queries if i.get("expected_open_now") is True]
        for item in open_now_cases:
            intent = _regex_fallback(item["query"])
            assert intent.filters.open_now is True, f"Expected open_now for: {item['query']}"
