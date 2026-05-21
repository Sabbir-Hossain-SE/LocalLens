"""
Tests for Module D — Review Aggregator.

Focus on pure logic: relative-time parsing, recency-weighted sentiment split,
recency score, and per-listing degradation when scraping is unavailable.

Tests are independent of `playwright` and `transformers` — both are mocked
or simply absent. The keyword sentiment fallback path is exercised end-to-end.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CACHE_DIR", str(ROOT / ".test_cache"))

from app.models.business import BusinessListing, Review, ReviewData
from app.modules.review_aggregator import (
    RECENCY_CUTOFF,
    RECENCY_WEIGHT_BOOST,
    ReviewAggregator,
    _keyword_sentiment,
    _parse_relative_time,
)


# ---------------------------------------------------------------------------
# Relative-time parsing
# ---------------------------------------------------------------------------

class TestParseRelativeTime:
    def test_a_month_ago(self) -> None:
        ts = _parse_relative_time("a month ago")
        assert ts is not None
        delta = datetime.now(timezone.utc) - ts
        assert timedelta(days=28) <= delta <= timedelta(days=31)

    def test_three_weeks_ago(self) -> None:
        ts = _parse_relative_time("posted 3 weeks ago about the food")
        assert ts is not None
        assert (datetime.now(timezone.utc) - ts) >= timedelta(days=20)

    def test_no_match(self) -> None:
        assert _parse_relative_time("yesterday") is None
        assert _parse_relative_time("") is None
        assert _parse_relative_time("the food was great") is None

    def test_an_hour_ago(self) -> None:
        ts = _parse_relative_time("an hour ago")
        assert ts is not None
        assert (datetime.now(timezone.utc) - ts) <= timedelta(hours=2)


# ---------------------------------------------------------------------------
# Keyword sentiment
# ---------------------------------------------------------------------------

class TestKeywordSentiment:
    def test_positive_dominant(self) -> None:
        label, score = _keyword_sentiment("great food and friendly staff")
        assert label == "POSITIVE"
        assert score >= 0.5

    def test_negative_dominant(self) -> None:
        label, score = _keyword_sentiment("terrible service, slow and rude")
        assert label == "NEGATIVE"
        assert score < 0.5

    def test_neutral_default_positive(self) -> None:
        label, score = _keyword_sentiment("we went there")
        assert label == "POSITIVE"
        assert score == 0.5


# ---------------------------------------------------------------------------
# Recency-weighted sentiment split
# ---------------------------------------------------------------------------

def _mk_listing(reviews: list[Review]) -> BusinessListing:
    return BusinessListing(
        id="t_1", name="Test Cafe", category="cafe", source="overpass",
        review_data=ReviewData(reviews=reviews, sample_reviews=[r.text for r in reviews]),
    )


class TestWeightedSentiment:
    def test_all_positive_no_timestamps(self) -> None:
        rs = [Review(text="x", sentiment_label="POSITIVE") for _ in range(4)]
        pos, neg = ReviewAggregator._weighted_sentiment_split(rs)
        assert pos == 100.0 and neg == 0.0

    def test_recent_positives_outweigh_old_negatives(self) -> None:
        now = datetime.now(timezone.utc)
        rs = [
            Review(text="great", sentiment_label="POSITIVE", timestamp=now - timedelta(days=10)),
            Review(text="awful", sentiment_label="NEGATIVE", timestamp=now - timedelta(days=400)),
        ]
        pos, neg = ReviewAggregator._weighted_sentiment_split(rs)
        # Recent positive counts 1.5x; old negative counts 1.0x → pos > 50 %
        assert pos > 55.0
        assert neg < 45.0

    def test_empty(self) -> None:
        assert ReviewAggregator._weighted_sentiment_split([]) == (50.0, 50.0)


# ---------------------------------------------------------------------------
# Recency score
# ---------------------------------------------------------------------------

class TestRecencyScore:
    def test_no_timestamps_returns_neutral(self) -> None:
        rs = [Review(text="x") for _ in range(3)]
        assert ReviewAggregator._recency_score(rs) == 0.5

    def test_all_recent_full_score(self) -> None:
        now = datetime.now(timezone.utc)
        rs = [Review(text="x", timestamp=now - timedelta(days=10)) for _ in range(3)]
        assert ReviewAggregator._recency_score(rs) == 1.0

    def test_all_old_zero_score(self) -> None:
        now = datetime.now(timezone.utc)
        rs = [Review(text="x", timestamp=now - timedelta(days=400)) for _ in range(3)]
        assert ReviewAggregator._recency_score(rs) == 0.0

    def test_half_recent(self) -> None:
        now = datetime.now(timezone.utc)
        rs = [
            Review(text="a", timestamp=now - timedelta(days=10)),
            Review(text="b", timestamp=now - timedelta(days=400)),
        ]
        assert ReviewAggregator._recency_score(rs) == 0.5


# ---------------------------------------------------------------------------
# Aggregate — end-to-end on a single listing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_no_scraping_falls_back_to_snippets() -> None:
    """When playwright is unavailable, aggregator uses pre-attached snippets."""
    listing = BusinessListing(
        id="t_1",
        name="Joe's Pizza",
        category="restaurant",
        source="duckduckgo",
        review_data=ReviewData(
            sample_reviews=["amazing crust and friendly service", "average"],
            total_reviews=2,
        ),
        maps_url=None,  # skips Playwright scrape
    )
    agg = ReviewAggregator(scrape_concurrency=1)
    out = await agg.aggregate([listing])
    assert len(out) == 1
    result = out[0]
    # Sentiment ran on the snippets
    assert result.review_data.positive_percentage > 0
    assert result.review_data.recurring_themes  # at least one theme detected
    # Low confidence flag set because total_reviews < 5
    assert result.review_data.low_confidence is True


def test_recency_constants_are_sane() -> None:
    """Guard against accidental edits to the recency policy."""
    assert RECENCY_CUTOFF == timedelta(days=180)
    assert RECENCY_WEIGHT_BOOST > 1.0
