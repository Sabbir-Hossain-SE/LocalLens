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
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.models.intent import HistoryTurn, ParsedIntent, SearchFilters
from app.utils.logger import get_logger
from app.utils.tracing import trace_llm

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


# Words/phrases that signal a follow-up refinement of a prior result set.
# When any of these match AND a prior turn exists, the new intent inherits
# category + location from the prior turn.
_FOLLOWUP_PATTERNS = [
    r"\bcheaper\b", r"\bmore expensive\b", r"\baffordable", r"\bbudget\b",
    r"\bopen now\b", r"\bopen today\b", r"\bopen\s+(?:late|right now)",
    r"\bhigher rated\b", r"\bbetter rated\b", r"\bonly\s+\d+", r"\bmore (?:options|results)\b",
    r"\bshow me (?:more|cheaper|other)", r"\bany (?:other|more)", r"\bdifferent\b",
    r"\bcloser\b", r"\bnearby\b", r"\bwithin\b", r"\bsame (?:area|place)\b",
    r"\bjust the\b", r"\bonly (?:the )?ones?\b",
]
_FOLLOWUP_RE = re.compile("|".join(_FOLLOWUP_PATTERNS), re.IGNORECASE)


def _detect_followup(query: str, history: Optional[List[HistoryTurn]]) -> bool:
    """
    Heuristic: a query is a follow-up if there's prior history AND either
      - it matches a follow-up phrase pattern, OR
      - it's very short (≤4 tokens) and lacks an explicit category noun.
    """
    if not history:
        return False
    if _FOLLOWUP_RE.search(query):
        return True
    tokens = [t for t in re.findall(r"[a-z]+", query.lower()) if len(t) > 1]
    # Short query without a recognised category keyword = likely a refinement
    if len(tokens) <= 4 and not any(t in _CATEGORY_KEYWORDS for t in tokens):
        return True
    return False


class IntentParser:
    """
    Parses raw user queries into structured ParsedIntent objects.

    Primary path: LangChain + Ollama/Groq with JSON mode.
    Fallback path: hand-crafted regex parser.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm: Any = None  # Lazy-initialised
        self._classifier: Any = None
        self._classifier_id2label: Optional[Dict[int, str]] = None
        self._classifier_checked = False

    # ------------------------------------------------------------------
    # Fast path — fine-tuned DistilBERT classifier (PDF §7.1)
    # ------------------------------------------------------------------

    def _init_classifier(self) -> Optional[Any]:
        """Try to load the fine-tuned intent classifier exactly once."""
        if self._classifier_checked:
            return self._classifier
        self._classifier_checked = True
        try:
            import json as _json
            from pathlib import Path as _Path

            from transformers import (  # type: ignore
                AutoTokenizer,
                AutoModelForSequenceClassification,
                pipeline as hf_pipeline,
            )

            model_dir = _Path(__file__).resolve().parents[2] / "models" / "intent_classifier"
            if not (model_dir / "config.json").exists():
                logger.info("intent_classifier_unavailable", path=str(model_dir))
                return None

            label_map_file = model_dir / "label_map.json"
            if label_map_file.exists():
                self._classifier_id2label = {
                    int(k): v for k, v in _json.loads(label_map_file.read_text())["id2label"].items()
                }

            tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
            model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
            self._classifier = hf_pipeline(
                "text-classification",
                model=model,
                tokenizer=tokenizer,
                truncation=True,
                max_length=64,
                top_k=1,
            )
            logger.info("intent_classifier_ready", path=str(model_dir))
        except Exception as exc:
            logger.info("intent_classifier_init_failed", error=str(exc))
            self._classifier = None
        return self._classifier

    def _classify_category(self, query: str) -> Optional[tuple[str, float]]:
        """Return (label, confidence) if the classifier is ready and confident."""
        clf = self._init_classifier()
        if clf is None:
            return None
        try:
            preds = clf(query)
            # `top_k=1` returns a list of dicts (or list-of-list depending on version)
            top = preds[0] if isinstance(preds[0], dict) else preds[0][0]
            label = top["label"]
            score = float(top["score"])
            # Resolve label index → category if the model returned LABEL_0 style ids
            if label.startswith("LABEL_") and self._classifier_id2label:
                label = self._classifier_id2label.get(int(label.split("_")[1]), label)
            return (label, score)
        except Exception as exc:
            logger.warning("intent_classifier_inference_error", error=str(exc))
            return None

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

    @trace_llm("intent_parser.call_llm")
    def _call_llm(
        self, query: str, prev: Optional[HistoryTurn] = None
    ) -> Optional[Dict[str, Any]]:
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
        if prev is not None:
            prompt = (
                f"Previous turn — query: {prev.query!r}, category: {prev.category!r}, "
                f"location: {prev.location!r}.\n"
                "If the new query is a follow-up (e.g. 'cheaper', 'open now', 'more like that'), "
                "REUSE the previous category and location instead of defaulting to 'restaurant' / 'near_me'.\n\n"
                + prompt
            )

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

    async def parse(
        self,
        query: str,
        history: Optional[List[HistoryTurn]] = None,
    ) -> ParsedIntent:
        """
        Parse a natural-language query into a ParsedIntent.

        Tries the LLM first; falls back to regex parsing if the LLM
        is unavailable or returns unparseable output. When ``history`` is
        provided, follow-up phrases ("cheaper", "open now", "show me more")
        inherit the prior turn's category/location instead of defaulting
        to "restaurant" / "near_me".

        Parameters
        ----------
        query:
            Raw user query string (e.g. "best sushi near me open now").
        history:
            Optional list of prior turns from the same chat session. Only
            the most recent turn is currently used for follow-up detection.

        Returns
        -------
        ParsedIntent
            Structured representation of the search intent.
        """
        logger.info("intent_parsing_start", query=query[:80])
        is_followup = _detect_followup(query, history)
        prev = history[-1] if history else None
        intent: Optional[ParsedIntent] = None

        # 1. FASTEST PATH — fine-tuned DistilBERT classifier (PDF §7.1).
        #    Only used when confidence ≥ 0.7 AND there's no follow-up history
        #    to layer on (follow-ups need the LLM's contextual reasoning).
        if not is_followup:
            clf = self._classify_category(query)
            if clf is not None and clf[1] >= 0.7:
                category, score = clf
                # Build the rest of the intent from the regex parser, then
                # override the category with the classifier's prediction.
                base = _regex_fallback(query)
                intent = base.model_copy(
                    update={"category": category, "confidence": score}
                )
                logger.info(
                    "intent_parsed_classifier",
                    category=category,
                    confidence=score,
                )

        # 2. LLM path (still the most flexible).
        if intent is None:
            llm_data = self._call_llm(query, prev=prev)
            if llm_data:
                try:
                    intent = self._build_from_llm_data(llm_data, raw_query=query)
                    logger.info(
                        "intent_parsed_llm",
                        category=intent.category,
                        location=intent.location,
                        confidence=intent.confidence,
                    )
                except Exception as exc:
                    logger.warning("intent_parser_build_failed", error=str(exc))

        # 3. Regex fallback (always works).
        if intent is None:
            intent = _regex_fallback(query)
            logger.info(
                "intent_parsed_regex",
                category=intent.category,
                location=intent.location,
                confidence=intent.confidence,
            )

        # Layer follow-up context: inherit category/location from prior turn
        # when the current query doesn't specify them.
        if is_followup and prev:
            inherited = intent.model_copy(
                update={
                    "category": prev.category or intent.category,
                    "location": prev.location or intent.location,
                    "is_followup": True,
                }
            )
            logger.info(
                "intent_followup_applied",
                inherited_category=prev.category,
                inherited_location=prev.location,
            )
            return inherited
        return intent
