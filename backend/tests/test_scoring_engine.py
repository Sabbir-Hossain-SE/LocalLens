"""
Tests for the scoring engine module.

Validates weight loading, signal normalisation, composite score calculation,
and ranking behaviour under various configurations.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.business import BusinessListing, ReviewData
from app.models.intent import ParsedIntent, SearchFilters
from app.modules.scoring_engine import (
    ScoringEngine,
    _compute_composite,
    _get_weights_for_category,
    _load_weights,
    _normalise_review_count,
    _normalise_sentiment,
    _normalise_star_rating,
)


# ---------------------------------------------------------------------------
# Normaliser unit tests
# ---------------------------------------------------------------------------

class TestNormalisers:
    """Unit tests for each signal normaliser."""

    def test_star_rating_5_is_1(self):
        assert _normalise_star_rating(5.0) == 1.0

    def test_star_rating_0_is_0(self):
        assert _normalise_star_rating(0.0) == 0.0

    def test_star_rating_none_is_0(self):
        assert _normalise_star_rating(None) == 0.0

    def test_star_rating_3_is_06(self):
        assert abs(_normalise_star_rating(3.0) - 0.6) < 0.001

    def test_review_count_100_is_1(self):
        assert _normalise_review_count(100) == 1.0

    def test_review_count_50_is_05(self):
        assert abs(_normalise_review_count(50) - 0.5) < 0.001

    def test_review_count_0_is_0(self):
        assert _normalise_review_count(0) == 0.0

    def test_review_count_over_saturation_capped(self):
        assert _normalise_review_count(500) == 1.0

    def test_sentiment_100pct_is_1(self):
        assert _normalise_sentiment(100.0) == 1.0

    def test_sentiment_0pct_is_0(self):
        assert _normalise_sentiment(0.0) == 0.0

    def test_sentiment_75pct(self):
        assert abs(_normalise_sentiment(75.0) - 0.75) < 0.001


# ---------------------------------------------------------------------------
# Weight loading tests
# ---------------------------------------------------------------------------

class TestLoadWeights:
    """Tests for the YAML weight loading function."""

    def test_loads_from_yaml_file(self):
        """The real scoring_weights.yaml should load without error."""
        weights = _load_weights()
        assert "default" in weights
        assert "star_rating" in weights["default"]

    def test_default_weights_sum_to_one(self):
        """The default weights must sum to approximately 1.0."""
        weights = _load_weights()
        default = weights["default"]
        total = sum(default.values())
        assert abs(total - 1.0) < 0.01

    def test_missing_file_returns_fallback(self):
        """A missing YAML file should return the hardcoded defaults."""
        weights = _load_weights(Path("/nonexistent/path/weights.yaml"))
        assert "default" in weights

    def test_custom_yaml_loaded(self):
        """A custom YAML file should override the defaults."""
        custom = {
            "default": {
                "star_rating": 0.50,
                "review_count": 0.25,
                "sentiment_score": 0.15,
                "recency_signal": 0.10,
            },
            "category_overrides": {},
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(custom, f)
            tmp_path = Path(f.name)

        loaded = _load_weights(tmp_path)
        assert loaded["default"]["star_rating"] == 0.50
        tmp_path.unlink()


class TestGetWeightsForCategory:
    """Tests for per-category weight selection."""

    @pytest.fixture
    def weights_config(self):
        return {
            "default": {
                "star_rating": 0.40,
                "review_count": 0.30,
                "sentiment_score": 0.20,
                "recency_signal": 0.10,
            },
            "category_overrides": {
                "restaurant": {
                    "star_rating": 0.45,
                    "review_count": 0.25,
                    "sentiment_score": 0.20,
                    "recency_signal": 0.10,
                }
            },
        }

    def test_exact_match_category_override(self, weights_config):
        weights = _get_weights_for_category(weights_config, "restaurant")
        assert weights["star_rating"] == 0.45

    def test_unknown_category_returns_default(self, weights_config):
        weights = _get_weights_for_category(weights_config, "submarine_sandwich_shop")
        assert weights["star_rating"] == 0.40

    def test_case_insensitive_lookup(self, weights_config):
        weights = _get_weights_for_category(weights_config, "RESTAURANT")
        assert weights["star_rating"] == 0.45


# ---------------------------------------------------------------------------
# Composite score tests
# ---------------------------------------------------------------------------

def _make_listing(
    name: str = "Test Place",
    rating: Optional[float] = 4.5,
    review_count: int = 80,
    positive_pct: float = 85.0,
    recency: float = 0.7,
) -> BusinessListing:
    return BusinessListing(
        id="test_1",
        name=name,
        category="cafe",
        source="overpass",
        review_data=ReviewData(
            average_rating=rating,
            total_reviews=review_count,
            positive_percentage=positive_pct,
            recency_score=recency,
        ),
    )


class TestComputeComposite:
    """Unit tests for the composite scoring formula."""

    def test_perfect_listing_scores_near_100(self):
        listing = _make_listing(rating=5.0, review_count=100, positive_pct=100.0, recency=1.0)
        weights = {"star_rating": 0.40, "review_count": 0.30, "sentiment_score": 0.20, "recency_signal": 0.10}
        score = _compute_composite(listing, weights)
        assert score >= 95.0

    def test_zero_listing_scores_near_0(self):
        listing = _make_listing(rating=0.0, review_count=0, positive_pct=0.0, recency=0.0)
        weights = {"star_rating": 0.40, "review_count": 0.30, "sentiment_score": 0.20, "recency_signal": 0.10}
        score = _compute_composite(listing, weights)
        assert score <= 5.0

    def test_score_in_valid_range(self):
        listing = _make_listing()
        weights = {"star_rating": 0.40, "review_count": 0.30, "sentiment_score": 0.20, "recency_signal": 0.10}
        score = _compute_composite(listing, weights)
        assert 0.0 <= score <= 100.0

    def test_higher_rating_gives_higher_score(self):
        low = _make_listing(rating=2.0, review_count=50)
        high = _make_listing(rating=5.0, review_count=50)
        weights = {"star_rating": 0.40, "review_count": 0.30, "sentiment_score": 0.20, "recency_signal": 0.10}
        assert _compute_composite(high, weights) > _compute_composite(low, weights)

    def test_more_reviews_gives_higher_score(self):
        few = _make_listing(rating=4.0, review_count=5)
        many = _make_listing(rating=4.0, review_count=95)
        weights = {"star_rating": 0.40, "review_count": 0.30, "sentiment_score": 0.20, "recency_signal": 0.10}
        assert _compute_composite(many, weights) > _compute_composite(few, weights)

    def test_no_rating_penalises_score(self):
        with_rating = _make_listing(rating=4.0)
        without_rating = _make_listing(rating=None)
        weights = {"star_rating": 0.40, "review_count": 0.30, "sentiment_score": 0.20, "recency_signal": 0.10}
        assert _compute_composite(with_rating, weights) > _compute_composite(without_rating, weights)


# ---------------------------------------------------------------------------
# ScoringEngine integration tests
# ---------------------------------------------------------------------------

def _make_intent(category="cafe", count=5, sort_by="rating") -> ParsedIntent:
    return ParsedIntent(
        category=category,
        count=count,
        sort_by=sort_by,
        location="near_me",
        raw_query=f"best {category} near me",
    )


class TestScoringEngine:
    """Integration tests for the full ScoringEngine class."""

    def test_returns_correct_count(self):
        engine = ScoringEngine()
        listings = [_make_listing(name=f"Place {i}", rating=float(i % 5)) for i in range(10)]
        intent = _make_intent(count=3)
        ranked = engine.score_and_rank(listings, intent)
        assert len(ranked) == 3

    def test_ranks_are_sequential_1_based(self):
        engine = ScoringEngine()
        listings = [_make_listing(name=f"Place {i}") for i in range(5)]
        intent = _make_intent(count=5)
        ranked = engine.score_and_rank(listings, intent)
        ranks = [b.rank for b in ranked]
        assert ranks == list(range(1, 6))

    def test_sorted_by_score_descending(self):
        engine = ScoringEngine()
        listings = [
            _make_listing("A", rating=2.0, review_count=10),
            _make_listing("B", rating=5.0, review_count=100),
            _make_listing("C", rating=3.5, review_count=50),
        ]
        intent = _make_intent(count=3)
        ranked = engine.score_and_rank(listings, intent)
        scores = [b.composite_score for b in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_first_ranked_is_highest_score(self):
        engine = ScoringEngine()
        listings = [
            _make_listing("Low", rating=1.0, review_count=5),
            _make_listing("High", rating=5.0, review_count=100),
        ]
        intent = _make_intent(count=2)
        ranked = engine.score_and_rank(listings, intent)
        assert ranked[0].name == "High"
        assert ranked[0].rank == 1

    def test_sort_by_reviews_mode(self):
        """sort_by='reviews' should order by total_reviews count."""
        engine = ScoringEngine()
        listings = [
            _make_listing("Few", rating=4.5, review_count=5),
            _make_listing("Many", rating=3.0, review_count=500),
        ]
        intent = _make_intent(count=2, sort_by="reviews")
        ranked = engine.score_and_rank(listings, intent)
        assert ranked[0].name == "Many"

    def test_empty_listings_returns_empty(self):
        engine = ScoringEngine()
        intent = _make_intent(count=5)
        ranked = engine.score_and_rank([], intent)
        assert ranked == []

    def test_composite_score_set_on_each_listing(self):
        engine = ScoringEngine()
        listings = [_make_listing(f"Place {i}") for i in range(3)]
        intent = _make_intent(count=3)
        ranked = engine.score_and_rank(listings, intent)
        for listing in ranked:
            assert listing.composite_score >= 0.0

    def test_restaurant_category_uses_override_weights(self):
        """Restaurant category override should be applied from YAML."""
        engine = ScoringEngine()
        listings = [_make_listing("Bistro", rating=4.5, review_count=80)]
        intent = _make_intent(category="restaurant", count=1)
        ranked = engine.score_and_rank(listings, intent)
        # Just verify no errors and score is set
        assert len(ranked) == 1
        assert ranked[0].composite_score > 0

    def test_reload_weights_does_not_raise(self):
        """reload_weights should run without error."""
        engine = ScoringEngine()
        engine.reload_weights()  # Should not raise
