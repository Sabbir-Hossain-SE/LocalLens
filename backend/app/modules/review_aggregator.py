"""
Module D – Review Aggregator.

Enriches each BusinessListing with sentiment-analysed review data.

Pipeline:
  1. Scrape review text + timestamps + star ratings from the business's public
     Google Maps page via Playwright (when ``playwright`` is installed).
  2. Run sentiment analysis: DistilBERT SST-2 if ``transformers`` is available,
     else keyword fallback.
  3. Apply recency weighting: reviews from the last 6 months count 1.5x in the
     positive_percentage calculation (PDF Module D requirement).
  4. Compute derived signals: positive/negative percentages, recurring themes,
     low-confidence flag with explicit reason.

Every scrape and inference path is wrapped in try/except so that a failure for
one listing never aborts the pipeline — the listing simply falls back to its
pre-existing snippet data (e.g. DuckDuckGo snippets).
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

from app.models.business import BusinessListing, Review, ReviewData
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

# Reviews newer than this cutoff are weighted RECENCY_WEIGHT_BOOST x for
# positive_percentage (PDF Module D: "reviews from the last 6 months are
# weighted more heavily").
RECENCY_CUTOFF = timedelta(days=180)
RECENCY_WEIGHT_BOOST = 1.5


def _keyword_sentiment(text: str) -> Tuple[str, float]:
    """Classify a review snippet using keyword matching (fallback path)."""
    words = set(re.sub(r"[^a-z ]", "", text.lower()).split())
    pos_hits = len(words & _POSITIVE_KEYWORDS)
    neg_hits = len(words & _NEGATIVE_KEYWORDS)
    total = pos_hits + neg_hits
    if total == 0:
        return ("POSITIVE", 0.5)
    score = pos_hits / total
    label = "POSITIVE" if score >= 0.5 else "NEGATIVE"
    return (label, score)


def _extract_themes(reviews: List[str]) -> List[str]:
    """Return the top recurring themes mentioned across a set of reviews."""
    theme_counts: dict[str, int] = {}
    combined = " ".join(reviews).lower()
    for pattern, label in _THEME_PATTERNS.items():
        if re.search(pattern, combined):
            theme_counts[label] = theme_counts.get(label, 0) + 1
    sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
    return [t[0] for t in sorted_themes[:4]]


# ---------------------------------------------------------------------------
# DistilBERT sentiment pipeline — lazy singleton
# ---------------------------------------------------------------------------

_sentiment_pipeline: Any = None
_transformers_available = False
_transformers_checked = False


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


def _analyse_sentiment(texts: List[str]) -> List[Tuple[str, float]]:
    """Run sentiment analysis with DistilBERT, falling back to keywords on failure."""
    global _transformers_checked
    if not _transformers_checked:
        _try_load_transformers()
        _transformers_checked = True

    if _transformers_available and _sentiment_pipeline and texts:
        try:
            preds = _sentiment_pipeline(texts)
            return [(p["label"], float(p["score"])) for p in preds]
        except Exception as exc:
            logger.warning("transformers_inference_error", error=str(exc))

    return [_keyword_sentiment(t) for t in texts]


# ---------------------------------------------------------------------------
# Relative-time parser ("3 weeks ago" → datetime)
# ---------------------------------------------------------------------------

_REL_TIME_RE = re.compile(
    r"(?P<num>\d+|a|an)\s*(?P<unit>second|minute|hour|day|week|month|year)s?\s*ago",
    re.IGNORECASE,
)
_UNIT_DELTAS = {
    "second": timedelta(seconds=1),
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}


def _parse_relative_time(s: str) -> Optional[datetime]:
    """Parse 'a month ago', '3 weeks ago', etc. into a UTC datetime."""
    if not s:
        return None
    m = _REL_TIME_RE.search(s)
    if not m:
        return None
    raw_num = m.group("num").lower()
    n = 1 if raw_num in ("a", "an") else int(raw_num)
    delta = _UNIT_DELTAS[m.group("unit").lower()] * n
    return datetime.now(timezone.utc) - delta


# ---------------------------------------------------------------------------
# Playwright-based review scraping (lazy import)
# ---------------------------------------------------------------------------

_playwright_available: Optional[bool] = None


def _check_playwright() -> bool:
    """Cache whether playwright is importable."""
    global _playwright_available
    if _playwright_available is not None:
        return _playwright_available
    try:
        import playwright.async_api  # noqa: F401
        _playwright_available = True
    except ImportError:
        logger.info("playwright_not_installed")
        _playwright_available = False
    return _playwright_available


async def _scrape_reviews_playwright(
    maps_url: str, max_reviews: int = 10, timeout_s: float = 12.0
) -> List[Review]:
    """Back-compatible wrapper returning only review texts."""
    reviews, _, _ = await _scrape_maps_details(maps_url, max_reviews, timeout_s)
    return reviews


def _parse_review_count(raw: str) -> int:
    """Parse review count strings like '1,234' or '(243)'."""
    try:
        return int(re.sub(r"[^0-9]", "", raw))
    except ValueError:
        return 0


def _extract_rating_count(text: str) -> tuple[Optional[float], int]:
    """Extract Google Maps average rating and review count from page text."""
    rating: Optional[float] = None
    total_reviews = 0

    rating_match = re.search(r"\b([1-5](?:\.\d)?)\s*(?:stars?|★)\b", text, re.I)
    if not rating_match:
        rating_match = re.search(r"\b([1-5]\.\d)\b", text)
    if rating_match:
        try:
            rating = float(rating_match.group(1))
        except ValueError:
            rating = None

    count_match = re.search(r"\(?([\d,]{2,})\)?\s*(?:reviews?|Google reviews?)", text, re.I)
    if count_match:
        total_reviews = _parse_review_count(count_match.group(1))

    return rating, total_reviews


async def _scrape_maps_details(
    maps_url: str, max_reviews: int = 10, timeout_s: float = 12.0
) -> tuple[List[Review], Optional[float], int]:
    """
    Scrape review text, average rating, and review count from Google Maps.

    Uses Playwright headless Chromium. Robust to layout changes: returns whatever
    review-like text it can find, with empty result on any failure.
    """
    if not _check_playwright():
        return ([], None, 0)

    from playwright.async_api import async_playwright  # type: ignore

    reviews: List[Review] = []
    rating: Optional[float] = None
    total_reviews = 0
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = await context.new_page()
            try:
                await page.goto(maps_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
                # Let the JS settle and reviews mount.
                await page.wait_for_timeout(2000)
                html = await page.content()
                page_text = await page.locator("body").inner_text(timeout=2000)
                rating, total_reviews = _extract_rating_count(page_text)
            finally:
                await context.close()
                await browser.close()
    except Exception as exc:
        logger.warning("playwright_scrape_error", url=maps_url, error=str(exc))
        return ([], None, 0)

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "lxml")
        # Heuristic: collect <span> blocks with reasonable length, then look
        # for sibling text containing "ago" for the timestamp.
        candidates = soup.find_all(["span", "div"])
        for el in candidates:
            text = (el.get_text() or "").strip()
            if not (20 <= len(text) <= 600):
                continue
            # crude review-ness filter
            if not any(w in text.lower() for w in ("the", "and", "was", "is", "it ", "i ")):
                continue
            # try to find a sibling/relative-time marker nearby
            parent_text = (el.parent.get_text() if el.parent else "") or ""
            ts = _parse_relative_time(parent_text) or _parse_relative_time(text)
            reviews.append(Review(text=text, timestamp=ts))
            if len(reviews) >= max_reviews:
                break
    except Exception as exc:
        logger.warning("review_html_parse_error", error=str(exc))

    return (reviews, rating, total_reviews)


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------


class ReviewAggregator:
    """
    Enriches BusinessListings with scraped reviews + DistilBERT sentiment.

    For listings whose `maps_url` is set (effectively every Overpass/DDG result)
    we attempt a Playwright scrape. If scraping is unavailable or fails, we
    fall back to whatever review snippets were already attached upstream.
    """

    def __init__(self, scrape_concurrency: int = 3) -> None:
        self._scrape_sem = asyncio.Semaphore(scrape_concurrency)

    async def aggregate(self, listings: List[BusinessListing]) -> List[BusinessListing]:
        """Add review data to every listing. Failures degrade gracefully per-listing."""
        tasks = [self._enrich_one(lst) for lst in listings]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        enriched: List[BusinessListing] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(
                    "review_aggregation_error", business=listings[i].name, error=str(r)
                )
                enriched.append(listings[i])
            else:
                enriched.append(r)  # type: ignore[arg-type]
        return enriched

    async def _enrich_one(self, listing: BusinessListing) -> BusinessListing:
        """Compute and attach ReviewData to a single listing."""
        # 1. Collect reviews — start from any pre-attached snippets, then
        #    augment via Playwright scrape if possible.
        scraped: List[Review] = []
        scraped_rating: Optional[float] = None
        scraped_total_reviews = 0
        if listing.maps_url:
            async with self._scrape_sem:
                scraped, scraped_rating, scraped_total_reviews = await _scrape_maps_details(
                    listing.maps_url
                )

        # Snippets already attached (DDG body, etc.) become Reviews without timestamps.
        prior = [
            Review(text=t) for t in (listing.review_data.sample_reviews or []) if t
        ]
        all_reviews: List[Review] = scraped + prior

        # 2. Sentiment
        texts = [r.text for r in all_reviews]
        if texts:
            sentiments = _analyse_sentiment(texts)
            for r, (label, score) in zip(all_reviews, sentiments):
                r.sentiment_label = label
                r.sentiment_score = score

        # 3. Recency-weighted positive/negative percentages
        positive_pct, negative_pct = self._weighted_sentiment_split(all_reviews)
        recency_score = self._recency_score(all_reviews)

        # 4. Themes
        themes = _extract_themes(texts) if texts else []

        # 5. Confidence
        total_reviews = max(
            listing.review_data.total_reviews,
            scraped_total_reviews,
            len(all_reviews),
        )
        avg_rating = listing.review_data.average_rating
        if avg_rating is None:
            avg_rating = scraped_rating
        low_confidence = total_reviews < 5 or avg_rating is None
        reason: Optional[str] = None
        if total_reviews == 0:
            reason = "No reviews found"
        elif total_reviews < 5:
            reason = f"Only {total_reviews} review(s) available"
        elif avg_rating is None:
            reason = "No rating data available"

        updated = ReviewData(
            total_reviews=total_reviews,
            average_rating=avg_rating,
            positive_percentage=round(positive_pct, 1),
            negative_percentage=round(negative_pct, 1),
            recurring_themes=themes,
            recency_score=round(recency_score, 2),
            sample_reviews=[r.text for r in all_reviews[:5]],
            reviews=all_reviews[:10],
            low_confidence=low_confidence,
            confidence_reason=reason,
        )
        return listing.model_copy(update={"review_data": updated})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _weighted_sentiment_split(reviews: List[Review]) -> Tuple[float, float]:
        """
        Compute positive% and negative% with recency weighting.

        Reviews newer than RECENCY_CUTOFF count RECENCY_WEIGHT_BOOST x.
        Reviews without a timestamp count 1x (conservative default).
        """
        if not reviews:
            return (50.0, 50.0)

        now = datetime.now(timezone.utc)
        pos_w = 0.0
        neg_w = 0.0
        for r in reviews:
            if r.sentiment_label is None:
                continue
            weight = 1.0
            if r.timestamp is not None:
                # Normalise to UTC-aware
                ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
                if (now - ts) <= RECENCY_CUTOFF:
                    weight = RECENCY_WEIGHT_BOOST
            if r.sentiment_label == "POSITIVE":
                pos_w += weight
            else:
                neg_w += weight

        total = pos_w + neg_w
        if total == 0:
            return (50.0, 50.0)
        return ((pos_w / total) * 100.0, (neg_w / total) * 100.0)

    @staticmethod
    def _recency_score(reviews: List[Review]) -> float:
        """
        Fraction of reviews newer than RECENCY_CUTOFF, in [0, 1].

        A business with all-fresh reviews scores 1.0; one with none in the last
        6 months scores 0.0. Reviews without timestamps are ignored from this
        calculation (do not count for or against recency).
        """
        timed = [r for r in reviews if r.timestamp is not None]
        if not timed:
            return 0.5  # unknown
        now = datetime.now(timezone.utc)
        recent = 0
        for r in timed:
            ts = r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)  # type: ignore[union-attr]
            if (now - ts) <= RECENCY_CUTOFF:
                recent += 1
        return recent / len(timed)
