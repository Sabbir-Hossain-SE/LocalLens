"""
Module A – Intent Parser.

Converts a raw natural-language user query into a structured ParsedIntent
by calling the configured LLM (Ollama or Groq via LangChain).  Falls back
to a hand-crafted regex parser if the LLM is unavailable or returns
unparseable output.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from app.config import get_settings
from app.models.intent import ParsedIntent, SearchFilters
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an intent parser for a local business search engine. \
Extract structured information from the user query.

Return a JSON object with ONLY these keys:
- category: the type of business/service (e.g. "sushi restaurant", "dentist", "co-working space")
- count: number of results requested (default 5 if not specified)
- location: the location string exactly as mentioned, or "near_me" if the user says "near me" / "nearby" / "close to me"
- radius_km: search radius in km (default 5, or extract from "within X km/miles")
- sort_by: "rating" (default), "distance", or "reviews"
- filters: object with open_now (bool), min_rating (float or null), price_level (null/"affordable"/"moderate"/"expensive"), max_distance_km (float or null)
- confidence: 0.0-1.0 how confident you are in the extraction

Respond with raw JSON only – no markdown, no commentary.

User query: {query}\
"""

# ---------------------------------------------------------------------------
# Category → OSM tag helpers (used by regex fallback)
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: Dict[str, str] = {
    "sushi": "sushi restaurant",
    "pizza": "pizza restaurant",
    "ramen": "ramen restaurant",
    "burger": "burger restaurant",
    "taco": "taco restaurant",
    "mexican": "mexican restaurant",
    "italian": "italian restaurant",
    "chinese": "chinese restaurant",
    "thai": "thai restaurant",
    "indian": "indian restaurant",
    "restaurant": "restaurant",
    "food": "restaurant",
    "eat": "restaurant",
    "cafe": "cafe",
    "coffee": "cafe",
    "bar": "bar",
    "pub": "bar",
    "dentist": "dentist",
    "doctor": "doctor",
    "clinic": "clinic",
    "hospital": "hospital",
    "pharmacy": "pharmacy",
    "gym": "gym",
    "fitness": "gym",
    "yoga": "yoga studio",
    "pilates": "pilates studio",
    "spa": "spa",
    "salon": "hair salon",
    "barber": "barber",
    "hotel": "hotel",
    "motel": "hotel",
    "grocery": "grocery store",
    "supermarket": "supermarket",
    "coworking": "coworking space",
    "co-working": "coworking space",
    "bank": "bank",
    "atm": "ATM",
    "park": "park",
    "library": "library",
    "school": "school",
    "gas": "gas station",
    "petrol": "gas station",
}


def _regex_fallback(query: str) -> ParsedIntent:
    """
    Regex-based intent parser used when the LLM is unavailable.

    Covers the most common query patterns:
    - "top 5 sushi restaurants in Seattle"
    - "best coffee near me"
    - "open now dentist within 3 km"
    """
    q = query.lower()

    # --- count ---
    count = 5
    count_match = re.search(r"\b(top|best|find|show|list)\s+(\d+)\b", q)
    if count_match:
        count = min(int(count_match.group(2)), 50)
    else:
        standalone = re.search(r"\b(\d+)\b", q)
        if standalone:
            count = min(int(standalone.group(1)), 50)

    # --- category ---
    category = "business"
    for kw, cat in _CATEGORY_KEYWORDS.items():
        if kw in q:
            category = cat
            break

    # --- location ---
    location = "near_me"
    near_me_patterns = [
        r"near me",
        r"nearby",
        r"close to me",
        r"around me",
        r"around here",
    ]
    for pat in near_me_patterns:
        if re.search(pat, q):
            location = "near_me"
            break
    else:
        in_match = re.search(r"\bin\s+([A-Za-z\s,]+?)(?:\s*$|\s+within|\s+open)", q)
        if in_match:
            location = in_match.group(1).strip()
        zip_match = re.search(r"\b(\d{5})\b", q)
        if zip_match:
            location = zip_match.group(1)

    # --- radius ---
    radius_km = 5.0
    radius_match = re.search(r"within\s+(\d+(?:\.\d+)?)\s*(km|mile|mi)", q)
    if radius_match:
        val = float(radius_match.group(1))
        unit = radius_match.group(2)
        radius_km = val if "km" in unit else val * 1.60934

    # --- sort_by ---
    sort_by = "rating"
    if "distance" in q or "closest" in q or "nearest" in q:
        sort_by = "distance"
    elif "review" in q or "most reviewed" in q:
        sort_by = "reviews"

    # --- filters ---
    open_now = bool(re.search(r"\bopen\s+now\b", q))
    min_rating: Optional[float] = None
    rating_match = re.search(r"rated?\s+(\d+(?:\.\d+)?)\s*\+?", q)
    if rating_match:
        min_rating = float(rating_match.group(1))

    price_level: Optional[str] = None
    if any(w in q for w in ["cheap", "affordable", "budget", "inexpensive"]):
        price_level = "affordable"
    elif any(
        w in q for w in ["expensive", "upscale", "fancy", "luxury", "fine dining"]
    ):
        price_level = "expensive"
    elif "moderate" in q or "mid-range" in q:
        price_level = "moderate"

    filters = SearchFilters(
        open_now=open_now, min_rating=min_rating, price_level=price_level
    )

    return ParsedIntent(
        category=category,
        count=count,
        location=location,
        radius_km=radius_km,
        sort_by=sort_by,
        filters=filters,
        raw_query=query,
        confidence=0.6,  # Lower confidence for regex parse
    )


class IntentParser:
    """
    Parses raw user queries into structured ParsedIntent objects.

    Primary path: LangChain + Ollama/Groq with JSON mode.
    Fallback path: hand-crafted regex parser.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm: Any = None  # Lazy-initialised

    def _init_llm(self) -> Optional[Any]:
        """Attempt to initialise the LangChain LLM.  Returns None on failure."""
        if self._llm is not None:
            return self._llm
        try:
            if self._settings.LLM_PROVIDER == "ollama":
                from langchain_community.llms import Ollama  # type: ignore

                self._llm = Ollama(
                    base_url=self._settings.OLLAMA_BASE_URL,
                    model=self._settings.LLM_MODEL,
                    format="json",
                    temperature=0,
                    tfs_z=0,
                )
                logger.info(
                    "intent_parser_llm_ready",
                    provider="ollama",
                    model=self._settings.LLM_MODEL,
                )
            elif self._settings.LLM_PROVIDER == "groq" and self._settings.GROQ_API_KEY:
                from langchain_groq import ChatGroq  # type: ignore

                self._llm = ChatGroq(
                    api_key=self._settings.GROQ_API_KEY,
                    model_name=self._settings.LLM_MODEL,
                )
                logger.info(
                    "intent_parser_llm_ready",
                    provider="groq",
                    model=self._settings.LLM_MODEL,
                )
            return self._llm
        except Exception as exc:
            logger.warning("intent_parser_llm_init_failed", error=str(exc))
            return None

    def _call_llm(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Call the LLM and parse its JSON response.

        Returns a dict on success, or None if the LLM is unavailable or
        the response cannot be parsed. Hard-caps at 8 seconds so the
        regex fallback triggers quickly when Ollama is unreachable.
        """
        import signal

        llm = self._init_llm()
        if llm is None:
            return None

        prompt = _SYSTEM_PROMPT.format(query=query)

        def _timeout_handler(signum: int, frame: Any) -> None:
            raise TimeoutError("LLM call timed out")

        try:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(60)
            try:
                response = llm.invoke(prompt)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            # LangChain may return a string or an AIMessage
            text = response.content if hasattr(response, "content") else str(response)
            # Strip potential markdown fences
            text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
            data: Dict[str, Any] = json.loads(text)
            return data
        except Exception as exc:
            logger.warning("intent_parser_llm_call_failed", error=str(exc))
            return None

    def _build_from_llm_data(
        self, data: Dict[str, Any], raw_query: str
    ) -> ParsedIntent:
        """Convert the LLM's raw JSON dict to a validated ParsedIntent."""
        filters_raw = data.get("filters", {}) or {}
        filters = SearchFilters(
            open_now=bool(filters_raw.get("open_now", False)),
            min_rating=filters_raw.get("min_rating"),
            price_level=filters_raw.get("price_level"),
            max_distance_km=filters_raw.get("max_distance_km"),
        )
        return ParsedIntent(
            category=str(data.get("category", "business")),
            count=int(data.get("count", 5)),
            location=str(data.get("location", "near_me")),
            radius_km=float(data.get("radius_km", 5.0)),
            sort_by=str(data.get("sort_by", "rating")),
            filters=filters,
            raw_query=raw_query,
            confidence=float(data.get("confidence", 0.9)),
        )

    async def parse(self, query: str) -> ParsedIntent:
        """
        Parse a natural-language query into a ParsedIntent.

        Tries the LLM first; falls back to regex parsing if the LLM
        is unavailable or returns unparseable output.

        Parameters
        ----------
        query:
            Raw user query string (e.g. "best sushi near me open now").

        Returns
        -------
        ParsedIntent
            Structured representation of the search intent.
        """
        logger.info("intent_parsing_start", query=query[:80])
        llm_data = self._call_llm(query)
        if llm_data:
            try:
                intent = self._build_from_llm_data(llm_data, raw_query=query)
                logger.info(
                    "intent_parsed_llm",
                    category=intent.category,
                    location=intent.location,
                    confidence=intent.confidence,
                )
                return intent
            except Exception as exc:
                logger.warning("intent_parser_build_failed", error=str(exc))

        # Regex fallback
        intent = _regex_fallback(query)
        logger.info(
            "intent_parsed_regex",
            category=intent.category,
            location=intent.location,
            confidence=intent.confidence,
        )
        return intent
