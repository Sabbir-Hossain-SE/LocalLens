"""
Module F – LLM Summarizer.

Generates a concise 2–3 sentence summary for each ranked BusinessListing.

Primary path:  LangChain + Ollama/Groq with an anti-hallucination prompt.
Fallback path: Template-based summary from structured data fields.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from app.config import get_settings
from app.models.business import BusinessListing
from app.models.intent import ParsedIntent
from app.utils.logger import get_logger
from app.utils.tracing import trace_llm

logger = get_logger(__name__)

_SUMMARY_PROMPT = """\
You are a factual business summary writer. Using ONLY the information provided below,
write a 2-3 sentence summary of this business. Do NOT add any facts not listed here.
Do NOT speculate or hallucinate details.

Business name: {name}
Category: {category}
Address: {address}
Average rating: {rating}
Total reviews: {total_reviews}
Positive review percentage: {positive_pct}%
Review themes: {themes}
Opening hours: {hours}
Phone: {phone}
Website: {website}

Write a helpful, factual summary:\
"""


# ---------------------------------------------------------------------------
# Hallucination verifier
# ---------------------------------------------------------------------------

# Words that are too generic to be considered factual claims worth verifying.
_GENERIC_TOKENS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by",
    "with", "from", "is", "are", "was", "were", "be", "been", "being", "has",
    "have", "had", "this", "that", "these", "those", "it", "its", "if", "as",
    "best", "place", "places", "spot", "spots", "great", "good", "well",
    "highly", "rated", "reviews", "review", "business", "stand", "out", "make",
    "makes", "who", "what", "where", "when", "why", "how", "you", "your",
    "they", "their", "them", "we", "our", "us", "all", "any", "some", "more",
    "most", "very", "really", "quite", "also", "just", "only", "open", "close",
    "closed", "near", "nearby", "find", "found", "according", "based",
}

# Patterns of "factual" content that must be grounded — capitalised multi-word
# phrases (proper nouns), numbers, percentages, prices.
_NOUN_PHRASE_RE = __import__("re").compile(r"\b([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,4})\b")
_NUMERIC_RE = __import__("re").compile(r"(\d+(?:\.\d+)?)\s*(?:%|stars?|reviews?|★|/5|out of 5)?")


def _verify_grounding(summary: str, listing: BusinessListing) -> bool:
    """
    Return True if every factual claim in *summary* is supported by the source.

    "Source" = the listing's name, category, address, opening_hours, phone,
    website, sample reviews, recurring themes, and the rating/review counts in
    review_data.

    Strategy:
      1. Extract candidate proper-noun phrases (>=2 capitalised words).
      2. Extract numeric claims (any number, with or without %/stars).
      3. Each must appear as a case-insensitive substring of the source bundle,
         OR (for numbers) match the rating / review count exactly.

    On any unsupported claim the summary is treated as hallucinated.
    """
    rd = listing.review_data
    source_parts = [
        listing.name or "",
        listing.category or "",
        listing.address or "",
        listing.opening_hours or "",
        listing.phone or "",
        listing.website or "",
        " ".join(rd.recurring_themes or []),
        " ".join(rd.sample_reviews or []),
    ]
    source_blob = " | ".join(source_parts).lower()

    # 1. Proper-noun phrase grounding
    for phrase in _NOUN_PHRASE_RE.findall(summary or ""):
        if phrase.lower() in source_blob:
            continue
        # Tolerate a phrase whose every token (minus generics) appears somewhere
        # in source — protects against legitimate paraphrases like "Joe Pizza"
        # vs "Joe's Pizza Restaurant".
        tokens = [t for t in phrase.lower().split() if t not in _GENERIC_TOKENS]
        if tokens and all(t in source_blob for t in tokens):
            continue
        logger.info("hallucination_phrase", phrase=phrase, name=listing.name)
        return False

    # 2. Numeric claim grounding
    allowed_numbers: set[str] = set()
    if rd.average_rating is not None:
        allowed_numbers.add(f"{rd.average_rating:.1f}")
        allowed_numbers.add(str(int(round(rd.average_rating))))
    allowed_numbers.add(str(rd.total_reviews))
    allowed_numbers.add(f"{rd.positive_percentage:.0f}")
    allowed_numbers.add(f"{rd.positive_percentage:.1f}")
    # Numbers already in source text (e.g. addresses, hours)
    for tok in source_blob.split():
        cleaned = tok.strip(",.;:()[]")
        if cleaned.replace(".", "", 1).isdigit():
            allowed_numbers.add(cleaned)

    for num in _NUMERIC_RE.findall(summary or ""):
        if num in allowed_numbers:
            continue
        # Tolerate integer/float equivalence ("4" matches "4.0")
        if "." in num and num.split(".")[0] in allowed_numbers:
            continue
        if num + ".0" in allowed_numbers:
            continue
        logger.info("hallucination_number", number=num, name=listing.name)
        return False

    return True


def _template_summary(listing: BusinessListing) -> str:
    """
    Generate a structured template summary when the LLM is unavailable.

    Uses only verifiable fields from the listing – never invents information.
    """
    rd = listing.review_data
    parts: List[str] = []

    # Sentence 1 – identity and location
    address_clause = f" located at {listing.address}" if listing.address else ""
    parts.append(f"{listing.name} is a {listing.category}{address_clause}.")

    # Sentence 2 – rating
    if rd.average_rating is not None:
        theme_clause = ""
        if rd.recurring_themes:
            theme_clause = f", with reviewers particularly praising {', '.join(rd.recurring_themes[:2])}"
        parts.append(
            f"It has a rating of {rd.average_rating}/5 based on {rd.total_reviews} "
            f"review{'s' if rd.total_reviews != 1 else ''}{theme_clause}."
        )
    elif rd.total_reviews > 0:
        parts.append(
            f"It has received {rd.total_reviews} review{'s' if rd.total_reviews != 1 else ''}."
        )
    else:
        parts.append("Rating information is currently unavailable.")

    # Sentence 3 – contact / hours
    contact_parts: List[str] = []
    if listing.opening_hours:
        contact_parts.append(f"open {listing.opening_hours}")
    if listing.phone:
        contact_parts.append(f"reachable at {listing.phone}")
    if contact_parts:
        parts.append(f"The business is {' and '.join(contact_parts)}.")

    return " ".join(parts)


class Summarizer:
    """
    Generates natural-language summaries for business listings.

    Tries the configured LLM; falls back to template summaries on failure.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm: Any = None

    def _init_llm(self) -> Optional[Any]:
        """Lazily initialise the LLM.  Returns None if unavailable."""
        if self._llm is not None:
            return self._llm
        try:
            if self._settings.LLM_PROVIDER == "ollama":
                from langchain_community.chat_models import ChatOllama  # type: ignore

                self._llm = ChatOllama(
                    base_url=self._settings.OLLAMA_BASE_URL,
                    model=self._settings.LLM_MODEL,
                )
            elif self._settings.LLM_PROVIDER == "groq" and self._settings.GROQ_API_KEY:
                from langchain_groq import ChatGroq  # type: ignore

                self._llm = ChatGroq(
                    api_key=self._settings.GROQ_API_KEY,
                    model_name=self._settings.LLM_MODEL,
                )
            logger.info("summarizer_llm_ready", provider=self._settings.LLM_PROVIDER)
            return self._llm
        except Exception as exc:
            logger.warning("summarizer_llm_init_failed", error=str(exc))
            return None

    def _build_prompt(self, listing: BusinessListing) -> str:
        """Format the anti-hallucination prompt with listing data."""
        rd = listing.review_data
        return _SUMMARY_PROMPT.format(
            name=listing.name,
            category=listing.category,
            address=listing.address or "Unknown",
            rating=f"{rd.average_rating:.1f}" if rd.average_rating else "N/A",
            total_reviews=rd.total_reviews,
            positive_pct=rd.positive_percentage,
            themes=(
                ", ".join(rd.recurring_themes)
                if rd.recurring_themes
                else "none mentioned"
            ),
            hours=listing.opening_hours or "Not available",
            phone=listing.phone or "Not available",
            website=listing.website or "Not available",
        )

    @trace_llm("summarizer.call_llm")
    def _call_llm_sync(self, prompt: str) -> Optional[str]:
        """Synchronous LLM call — no signal-based timeout (not safe in threads)."""
        llm = self._init_llm()
        if llm is None:
            return None
        try:
            response = llm.invoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)
            return text.strip()
        except Exception as exc:
            logger.warning("summarizer_llm_error", error=str(exc))
            return None

    async def _summarise_one(self, listing: BusinessListing) -> BusinessListing:
        """
        Generate a summary for a single listing with a 90-second async timeout.

        After generation, the text is run through ``_verify_grounding``. If a
        claim in the summary cannot be traced back to source data, we
        regenerate once with a stricter prompt, then fall back to the
        deterministic template summary.
        """
        prompt = self._build_prompt(listing)
        text = await self._invoke_with_timeout(prompt)

        if text and not _verify_grounding(text, listing):
            logger.warning(
                "summarizer_hallucination_detected",
                name=listing.name,
                summary=text[:200],
            )
            # One retry with a stricter prompt that re-emphasises grounding.
            stricter = (
                prompt
                + "\n\nIMPORTANT: Your previous response contained details NOT "
                "found above. Rewrite the summary using ONLY the verified facts "
                "listed above. Do not invent ANY details."
            )
            text = await self._invoke_with_timeout(stricter)
            if text and not _verify_grounding(text, listing):
                logger.warning("summarizer_hallucination_retry_failed", name=listing.name)
                text = None  # force template fallback

        if not text:
            text = _template_summary(listing)
        return listing.model_copy(update={"summary": text})

    async def _invoke_with_timeout(self, prompt: str) -> Optional[str]:
        """Run the sync LLM call in an executor under a 90-second async deadline."""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._call_llm_sync, prompt),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.warning("summarizer_timeout")
            return None

    async def summarise(
        self,
        listings: List[BusinessListing],
        intent: ParsedIntent,
    ) -> List[BusinessListing]:
        """
        Add a summary field to every listing in *listings*.

        Summaries are generated concurrently (up to 5 at a time) to limit
        latency while being polite to the LLM server.

        Parameters
        ----------
        listings:
            Scored, ranked listings ready for summarisation.
        intent:
            Not used directly, kept for future per-category prompt tweaks.

        Returns
        -------
        List[BusinessListing]
            Same listings with the ``summary`` field populated.
        """
        # Groq handles parallel requests cleanly; Ollama processes one at a time,
        # so going wider just queues. Tune concurrency by provider.
        concurrency = 3 if self._settings.LLM_PROVIDER == "groq" else 1
        logger.info(
            "summarizer_start",
            count=len(listings),
            provider=self._settings.LLM_PROVIDER,
            concurrency=concurrency,
        )
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded(listing: BusinessListing) -> BusinessListing:
            async with semaphore:
                return await self._summarise_one(listing)

        tasks = [_bounded(listing) for listing in listings]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        summarised: List[BusinessListing] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("summarizer_single_error", index=i, error=str(result))
                summarised.append(
                    listings[i].model_copy(
                        update={"summary": _template_summary(listings[i])}
                    )
                )
            else:
                summarised.append(result)  # type: ignore[arg-type]

        logger.info("summarizer_complete", count=len(summarised))
        return summarised
