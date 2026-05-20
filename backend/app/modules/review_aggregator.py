"""
Module D – Review Aggregator.

Enriches each BusinessListing with sentiment-analysed review data.

Sentiment pipeline:
  1. If ``transformers`` is installed → use DistilBERT SST-2 fine-tune.
  2. Otherwise → keyword-based sentiment scoring.

For OSM results the star rating may already be embedded as a tag.
All results are flagged low_confidence when fewer than 5 reviews are found.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.models.business import BusinessListing, ReviewData
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Keyword-based sentiment lists (fallback when transformers not available)
# ---------------------------------------------------------------------------

_POSITIVE_KEYWORDS = {
    "great", "excellent", "amazing", "fantastic", "wonderful", "love", "best",
    "perfect", "delicious", "tasty", "friendly", "helpful", "clean", "fast",
    "fresh", "good", "nice", "recommend", "outstanding", "superb", "awesome",
    "cozy", "comfortable", "efficient", "professional", "warm", "quality",
    "affordable", "reasonable", "genuine", "authentic",
}

_NEGATIVE_KEYWORDS = {
    "bad", "terrible", "horrible", "awful", "worst", "poor", "slow", "rude",
    "dirty", "cold", "stale", "overpriced", "expensive", "disappointing",
    "mediocre", "bland", "gross", "disgusting", "unfriendly", "unprofessional",
    "noisy", "cramped", "wait", "long", "never", "avoid", "waste",
}

# Recurring positive theme phrases mapped to labels
_THEME_PATTERNS = {
    r"\b(food|dish|meal|taste|flavou?r)\b": "great food",
    r"\b(service|staff|server|waiter|employee)\b": "good service",
    r"\b(clean|hygiene|spotless)\b": "clean environment",
    r"\b(fast|quick|speedy|prompt)\b": "fast service",
    r"\b(price|cheap|affordable|value)\b": "good value",
    r"\b(cozy|atmosphere|ambiance|vibe)\b": "nice atmosphere",
    r"\b(fresh|organic|local)\b": "fresh ingredients",
    r"\b(friendly|welcoming|warm)\b": "friendly staff",
}


def _keyword_sentiment(text: str) -> Tuple[str, float]:
    """
    Classify a review snippet as 'POSITIVE' or 'NEGATIVE' using keyword matching.

    Returns a tuple of (label, score) where score is in [0, 1].
    """
    words = set(re.sub(r"[^a-z ]", "", text.lower()).split())
    pos_hits = len(words & _POSITIVE_KEYWORDS)
    neg_hits = len(words & _NEGATIVE_KEYWORDS)
    total = pos_hits + neg_hits
    if total == 0:
        return ("POSITIVE", 0.5)  # Neutral default
    score = pos_hits / total
    label = "POSITIVE" if score >= 0.5 else "NEGATIVE"
    return (label, score)


def _extract_themes(reviews: List[str]) -> List[str]:
    """Extract the top recurring themes from a list of review snippets."""
    theme_counts: dict[str, int] = {}
    combined = " ".join(reviews).lower()
    for pattern, label in _THEME_PATTERNS.items():
        if re.search(pattern, combined):
            theme_counts[label] = theme_counts.get(label, 0) + 1
    # Sort by frequency, return top 4
    sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
    return [t[0] for t in sorted_themes[:4]]


# ---------------------------------------------------------------------------
# Transformer-based sentiment (optional)
# ---------------------------------------------------------------------------

_sentiment_pipeline = None
_transformers_available = False


def _try_load_transformers() -> None:
    """Attempt to load the DistilBERT sentiment pipeline exactly once."""
    global _sentiment_pipeline, _transformers_available
    try:
        from transformers import pipeline as hf_pipeline  # type: ignore

        _sentiment_pipeline = hf_pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            truncation=True,
            max_length=512,
        )
        _transformers_available = True
        logger.info("transformers_sentiment_loaded")
    except Exception as exc:
        logger.info("transformers_not_available", reason=str(exc))
        _transformers_available = False


_transformers_checked = False


def _analyse_sentiment(reviews: List[str]) -> List[Tuple[str, float]]:
    """
    Run sentiment analysis over a list of review snippets.

    Uses HuggingFace DistilBERT if available, falls back to keyword matching.
    Returns a list of (label, score) tuples.
    """
    global _transformers_checked
    if not _transformers_checked:
        _try_load_transformers()
        _transformers_checked = True

    results: List[Tuple[str, float]] = []
    if _transformers_available and _sentiment_pipeline:
        try:
            preds = _sentiment_pipeline(reviews)
            for pred in preds:
                results.append((pred["label"], float(pred["score"])))
            return results
        except Exception as exc:
            logger.warning("transformers_inference_error", error=str(exc))

    # Keyword fallback
    return [_keyword_sentiment(r) for r in reviews]


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------

class ReviewAggregator:
    """
    Enriches a list of BusinessListings with aggregated review sentiment data.

    For OSM results we attempt to read star ratings directly from OSM tags.
    For DuckDuckGo results we analyse the snippet text.
    """

    async def aggregate(self, listings: List[BusinessListing]) -> List[BusinessListing]:
        """
        Add review data to every listing in *listings*.

        Parameters
        ----------
        listings:
            Raw listings from the search agent (review_data will be populated).

        Returns
        -------
        List[BusinessListing]
            Same listings with review_data fields filled in.
        """
        enriched: List[BusinessListing] = []
        for listing in listings:
            try:
                enriched.append(await self._enrich_listing(listing))
            except Exception as exc:
                logger.warning("review_aggregation_error", business=listing.name, error=str(exc))
                enriched.append(listing)
        return enriched

    async def _enrich_listing(self, listing: BusinessListing) -> BusinessListing:
        """Compute and attach ReviewData to a single listing."""
        reviews = listing.review_data.sample_reviews.copy()
        avg_rating: Optional[float] = listing.review_data.average_rating
        total_reviews: int = listing.review_data.total_reviews

        # --- Sentiment analysis ---
        if reviews:
            sentiments = _analyse_sentiment(reviews)
            pos_count = sum(1 for label, _ in sentiments if label == "POSITIVE")
            neg_count = len(sentiments) - pos_count
            positive_pct = (pos_count / len(sentiments)) * 100 if sentiments else 0.0
            negative_pct = (neg_count / len(sentiments)) * 100 if sentiments else 0.0
        else:
            positive_pct = 50.0  # Default neutral
            negative_pct = 50.0

        # --- Themes ---
        themes = _extract_themes(reviews) if reviews else []

        # --- Low-confidence flag ---
        low_confidence = total_reviews < 5 or avg_rating is None
        confidence_reason: Optional[str] = None
        if total_reviews == 0:
            confidence_reason = "No reviews found"
        elif total_reviews < 5:
            confidence_reason = f"Only {total_reviews} review(s) available"
        elif avg_rating is None:
            confidence_reason = "No rating data available"

        updated_review = ReviewData(
            total_reviews=total_reviews,
            average_rating=avg_rating,
            positive_percentage=round(positive_pct, 1),
            negative_percentage=round(negative_pct, 1),
            recurring_themes=themes,
            recency_score=listing.review_data.recency_score,
            sample_reviews=reviews[:5],
            low_confidence=low_confidence,
            confidence_reason=confidence_reason,
        )

        # Return a new instance with updated review_data
        return listing.model_copy(update={"review_data": updated_review})
