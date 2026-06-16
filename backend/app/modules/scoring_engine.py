"""
Module E – Scoring Engine.

Computes a composite quality score (0–100) for each BusinessListing using
a configurable weighted formula loaded from ``config/scoring_weights.yaml``.

Default weights:
  star_rating    0.40
  review_count   0.30
  sentiment_score 0.20
  recency_signal  0.10

Each signal is normalised to [0, 1] before weighting.  Category-specific
weight overrides are applied when the business category matches a key in
the YAML file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.models.business import BusinessListing
from app.models.intent import ParsedIntent
from app.utils.embeddings import cosine_similarity, embed_batch, embed_text
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Absolute path to the YAML config (relative to this file's package root)
_WEIGHTS_FILE = Path(__file__).resolve().parents[2] / "config" / "scoring_weights.yaml"

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "star_rating": 0.40,
    "review_count": 0.30,
    "sentiment_score": 0.20,
    "recency_signal": 0.10,
}


def _load_weights(path: Path = _WEIGHTS_FILE) -> Dict[str, Any]:
    """
    Load scoring weights from the YAML file.

    Falls back to hardcoded defaults if the file is missing or malformed.
    """
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        logger.info("weights_loaded", path=str(path))
        return data or {}
    except FileNotFoundError:
        logger.warning("weights_file_not_found", path=str(path))
        return {"default": _DEFAULT_WEIGHTS, "category_overrides": {}}
    except Exception as exc:
        logger.warning("weights_load_error", error=str(exc))
        return {"default": _DEFAULT_WEIGHTS, "category_overrides": {}}


def _get_weights_for_category(
    weights_config: Dict[str, Any], category: str
) -> Dict[str, float]:
    """
    Return the weight dict to use for a given category.

    Checks ``category_overrides`` first; falls back to ``default``.
    """
    category_overrides: Dict[str, Dict[str, float]] = weights_config.get("category_overrides", {})
    category_lower = category.lower().strip()

    # Try exact match
    if category_lower in category_overrides:
        return dict(category_overrides[category_lower])

    # Try partial match (e.g. "sushi restaurant" matches "sushi")
    for key in category_overrides:
        if key in category_lower or category_lower in key:
            return dict(category_overrides[key])

    default = weights_config.get("default", _DEFAULT_WEIGHTS)
    return dict(default)


# ---------------------------------------------------------------------------
# Signal normalisers
# ---------------------------------------------------------------------------

def _normalise_star_rating(rating: Optional[float]) -> float:
    """Normalise a 0-5 star rating to [0, 1]."""
    if rating is None:
        return 0.0
    return max(0.0, min(1.0, rating / 5.0))


def _listing_description(listing: BusinessListing) -> str:
    """
    Build a free-text description used for semantic embedding.

    Concatenates the most discriminative attributes — name, category,
    recurring review themes, and a short sample of review text — into a
    single string. Keeps the length bounded so MiniLM's 256-token window
    isn't wasted on boilerplate.
    """
    rd = listing.review_data
    parts: List[str] = [listing.name, listing.category or ""]
    if rd.recurring_themes:
        parts.append(", ".join(rd.recurring_themes))
    if rd.sample_reviews:
        # First 1-2 review snippets, truncated
        parts.append(" ".join(rd.sample_reviews[:2])[:400])
    return " — ".join(p for p in parts if p)


def _normalise_review_count(count: int, saturation: int = 100) -> float:
    """
    Normalise review count using a saturation cap.

    Businesses with >= ``saturation`` reviews receive a score of 1.0.
    """
    return max(0.0, min(1.0, count / saturation))


def _normalise_sentiment(positive_pct: float) -> float:
    """Convert a positive-percentage (0-100) to [0, 1]."""
    return max(0.0, min(1.0, positive_pct / 100.0))


def _compute_composite(
    listing: BusinessListing, weights: Dict[str, float]
) -> float:
    """
    Calculate the weighted composite score for a single listing.

    Returns a float in [0, 100].
    """
    rd = listing.review_data

    star = _normalise_star_rating(rd.average_rating)
    review_count = _normalise_review_count(rd.total_reviews)
    sentiment = _normalise_sentiment(rd.positive_percentage)
    recency = rd.recency_score  # Already in [0, 1]

    # Total weight (may not sum to 1 if config has unexpected keys)
    total_weight = (
        weights.get("star_rating", 0.40)
        + weights.get("review_count", 0.30)
        + weights.get("sentiment_score", 0.20)
        + weights.get("recency_signal", 0.10)
    )
    if total_weight == 0:
        total_weight = 1.0

    raw_score = (
        star * weights.get("star_rating", 0.40)
        + review_count * weights.get("review_count", 0.30)
        + sentiment * weights.get("sentiment_score", 0.20)
        + recency * weights.get("recency_signal", 0.10)
    )

    return round((raw_score / total_weight) * 100, 2)


class ScoringEngine:
    """
    Assigns composite quality scores and ranks to a list of BusinessListings.

    Weights are loaded once from YAML at construction and cached for the
    lifetime of the engine instance.
    """

    def __init__(self) -> None:
        self._weights_config = _load_weights()

    def reload_weights(self) -> None:
        """Reload scoring weights from disk (useful after config edits)."""
        self._weights_config = _load_weights()
        logger.info("weights_reloaded")

    def score_and_rank(
        self,
        listings: List[BusinessListing],
        intent: ParsedIntent,
    ) -> List[BusinessListing]:
        """
        Score all listings and sort them by composite score descending.

        Parameters
        ----------
        listings:
            Listings that have already been enriched with review data.
        intent:
            The parsed intent (used to select category-specific weights
            and apply the ``sort_by`` preference).

        Returns
        -------
        List[BusinessListing]
            Same listings with composite_score and rank fields set,
            sorted by composite_score (highest first) or by the user's
            sort preference.
        """
        weights = _get_weights_for_category(self._weights_config, intent.category)
        logger.info(
            "scoring_start", count=len(listings), weights=weights, sort_by=intent.sort_by
        )

        # PDF §7.2 — semantic similarity becomes 30% of the composite when
        # the user asked for semantic ranking. It steals from review_count
        # (the least subjective of the four signals).
        semantic_scores: List[float] = [0.0] * len(listings)
        if intent.sort_by == "semantic":
            q_vec = embed_text(intent.raw_query)
            if q_vec is not None:
                descriptions = [_listing_description(b) for b in listings]
                vecs = embed_batch(descriptions)
                semantic_scores = [
                    cosine_similarity(q_vec, v) for v in vecs
                ]

        scored: List[BusinessListing] = []
        for i, listing in enumerate(listings):
            base = _compute_composite(listing, weights)
            if intent.sort_by == "semantic":
                # 70 % weighted composite + 30 % semantic similarity, all in 0–100
                score = round(0.7 * base + 0.3 * (semantic_scores[i] * 100), 2)
            else:
                score = base
            scored.append(listing.model_copy(update={"composite_score": score}))

        # Sort
        if intent.sort_by == "distance":
            # We don't have distance computed here; fall back to rating
            scored.sort(key=lambda b: b.composite_score, reverse=True)
        elif intent.sort_by == "reviews":
            scored.sort(key=lambda b: b.review_data.total_reviews, reverse=True)
        else:
            scored.sort(key=lambda b: b.composite_score, reverse=True)

        # Assign 1-based ranks and trim to requested count
        ranked: List[BusinessListing] = []
        for i, listing in enumerate(scored[: intent.count], start=1):
            ranked.append(listing.model_copy(update={"rank": i}))

        logger.info("scoring_complete", ranked=len(ranked))
        return ranked
