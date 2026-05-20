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
        """Generate a summary for a single listing with a 90-second async timeout."""
        prompt = self._build_prompt(listing)
        loop = asyncio.get_event_loop()
        try:
            text = await asyncio.wait_for(
                loop.run_in_executor(None, self._call_llm_sync, prompt),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            logger.warning("summarizer_timeout", name=listing.name)
            text = None
        if not text:
            text = _template_summary(listing)
        return listing.model_copy(update={"summary": text})

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
        logger.info("summarizer_start", count=len(listings))
        semaphore = asyncio.Semaphore(1)

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
