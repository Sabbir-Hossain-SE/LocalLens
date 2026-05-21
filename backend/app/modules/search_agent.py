"""
Module C – Multi-source Search Agent.

Searches for businesses using a waterfall of data sources:
  1. Overpass API (OpenStreetMap)  – structured, geo-accurate data
  2. DuckDuckGo text search        – fills gaps for niche categories
  3. Both sources are merged and deduplicated by fuzzy name matching.

Results are normalised to the BusinessListing schema before returning.
"""

from __future__ import annotations

import hashlib
import inspect
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx  # pyright: ignore[reportMissingImports]

from app.config import get_settings
from app.models.business import BusinessListing, ReviewData
from app.models.intent import ParsedIntent
from app.models.location import ResolvedLocation
from app.utils.cache import CacheManager
from app.utils.logger import get_logger
from app.utils.rate_limiter import MultiRateLimiter

logger = get_logger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_overpass_limiter = MultiRateLimiter.get("overpass", calls_per_second=0.5)
_ddg_limiter = MultiRateLimiter.get("duckduckgo", calls_per_second=0.5)

# ---------------------------------------------------------------------------
# Category → OSM tag mapping
# ---------------------------------------------------------------------------

# Each entry maps a keyword to (osm_key, osm_value, extra_tags)
# extra_tags are ANDed into the query filter (e.g. cuisine=sushi)
_CATEGORY_TO_OSM: Dict[str, Tuple[str, str, Optional[Dict[str, str]]]] = {
    "restaurant": ("amenity", "restaurant", None),
    "food": ("amenity", "restaurant", None),
    "sushi": ("amenity", "restaurant", {"cuisine": "sushi"}),
    "sushi restaurant": ("amenity", "restaurant", {"cuisine": "sushi"}),
    "pizza": ("amenity", "restaurant", {"cuisine": "pizza"}),
    "ramen": ("amenity", "restaurant", {"cuisine": "ramen"}),
    "burger": ("amenity", "restaurant", {"cuisine": "burger"}),
    "taco": ("amenity", "restaurant", {"cuisine": "mexican"}),
    "mexican restaurant": ("amenity", "restaurant", {"cuisine": "mexican"}),
    "italian restaurant": ("amenity", "restaurant", {"cuisine": "italian"}),
    "chinese restaurant": ("amenity", "restaurant", {"cuisine": "chinese"}),
    "thai restaurant": ("amenity", "restaurant", {"cuisine": "thai"}),
    "indian restaurant": ("amenity", "restaurant", {"cuisine": "indian"}),
    "cafe": ("amenity", "cafe", None),
    "coffee": ("amenity", "cafe", None),
    "coffee shop": ("amenity", "cafe", None),
    "bar": ("amenity", "bar", None),
    "pub": ("amenity", "pub", None),
    "dentist": ("amenity", "dentist", None),
    "doctor": ("amenity", "clinic", None),
    "clinic": ("amenity", "clinic", None),
    "hospital": ("amenity", "hospital", None),
    "pharmacy": ("amenity", "pharmacy", None),
    "gym": ("leisure", "fitness_centre", None),
    "fitness": ("leisure", "fitness_centre", None),
    "fitness centre": ("leisure", "fitness_centre", None),
    "yoga": ("leisure", "fitness_centre", {"sport": "yoga"}),
    "yoga studio": ("leisure", "fitness_centre", {"sport": "yoga"}),
    "pilates studio": ("leisure", "fitness_centre", {"sport": "pilates"}),
    "spa": ("leisure", "spa", None),
    "hair salon": ("shop", "hairdresser", None),
    "salon": ("shop", "hairdresser", None),
    "barber": ("shop", "hairdresser", None),
    "hotel": ("tourism", "hotel", None),
    "motel": ("tourism", "motel", None),
    "grocery store": ("shop", "supermarket", None),
    "grocery": ("shop", "supermarket", None),
    "supermarket": ("shop", "supermarket", None),
    "coworking space": ("office", "coworking", None),
    "coworking": ("office", "coworking", None),
    "co-working space": ("office", "coworking", None),
    "bank": ("amenity", "bank", None),
    "atm": ("amenity", "atm", None),
    "park": ("leisure", "park", None),
    "library": ("amenity", "library", None),
    "school": ("amenity", "school", None),
    "gas station": ("amenity", "fuel", None),
    "petrol station": ("amenity", "fuel", None),
}


def _get_osm_tags(category: str) -> Tuple[str, str, Optional[Dict[str, str]]]:
    """
    Map a category string to an OSM (key, value, extra_tags) triple.

    Tries exact match, then single-word tokenisation, then falls back to
    (amenity, restaurant) as a broad catch-all.
    """
    cat_lower = category.lower().strip()
    if cat_lower in _CATEGORY_TO_OSM:
        return _CATEGORY_TO_OSM[cat_lower]
    for word in cat_lower.split():
        if word in _CATEGORY_TO_OSM:
            return _CATEGORY_TO_OSM[word]
    return ("amenity", "restaurant", None)


def _build_overpass_query(
    bbox: "BoundingBox",  # type: ignore[name-defined]  # forward ref – imported below
    osm_key: str,
    osm_value: str,
    extra_tags: Optional[Dict[str, str]],
    timeout: int = 15,
) -> str:
    """
    Build an Overpass QL query that retrieves nodes and ways inside *bbox*.

    Parameters
    ----------
    bbox:
        Bounding box from the resolved location.
    osm_key / osm_value:
        Primary OSM tag filter (e.g. amenity=restaurant).
    extra_tags:
        Optional additional tag constraints (e.g. cuisine=sushi).
    timeout:
        Overpass server-side timeout in seconds.
    """
    s, w, n, e = bbox.south, bbox.west, bbox.north, bbox.east
    bbox_str = f"{s},{w},{n},{e}"

    extra = ""
    if extra_tags:
        extra = "".join(f'["{k}"="{v}"]' for k, v in extra_tags.items())

    query = (
        f"[out:json][timeout:{timeout}];"
        f"("
        f'  node["{osm_key}"="{osm_value}"]{extra}({bbox_str});'
        f'  way["{osm_key}"="{osm_value}"]{extra}({bbox_str});'
        f");"
        f"out center;"
    )
    return query


def _osm_element_to_listing(
    element: Dict[str, Any], category: str
) -> Optional[BusinessListing]:
    """Convert a single Overpass API element (node or way) to a BusinessListing."""
    tags = element.get("tags", {})
    name = tags.get("name")
    if not name:
        return None  # Skip unnamed features

    # Coordinates: nodes have lat/lon directly; ways have a centre object
    if element["type"] == "node":
        lat = element.get("lat")
        lng = element.get("lon")
    else:  # way
        centre = element.get("center", {})
        lat = centre.get("lat")
        lng = centre.get("lon")

    # Build address from OSM address tags
    addr_parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:city", ""),
        tags.get("addr:state", ""),
    ]
    address = " ".join(p for p in addr_parts if p).strip() or None

    phone = tags.get("phone") or tags.get("contact:phone")
    website = tags.get("website") or tags.get("contact:website")
    hours = tags.get("opening_hours")
    osm_id = str(element.get("id", ""))

    maps_url = _make_maps_url(name, address)

    return BusinessListing(
        id=f"osm_{osm_id}",
        name=name,
        address=address,
        lat=float(lat) if lat is not None else None,
        lng=float(lng) if lng is not None else None,
        category=category,
        phone=phone,
        website=website,
        opening_hours=hours,
        source="overpass",
        maps_url=maps_url,
    )


def _make_maps_url(name: str, address: Optional[str]) -> str:
    """Generate a Google Maps place search URL for a business.

    Using /maps/place/ instead of /maps/search/ navigates directly to the
    business profile page which exposes structured rating data more reliably.
    """
    query_parts = [name]
    if address:
        query_parts.append(address)
    query = urllib.parse.quote(" ".join(query_parts))
    return f"https://www.google.com/maps/place/{query}"


def _fuzzy_similar(a: str, b: str, threshold: float = 0.8) -> bool:
    """
    Cheap Jaccard-based token similarity check.

    Returns True if the two strings share enough tokens to be considered
    the same business (e.g. "Joe's Pizza" vs "Joe's Pizza Restaurant").
    """
    a_tokens = set(re.sub(r"[^a-z0-9 ]", "", a.lower()).split())
    b_tokens = set(re.sub(r"[^a-z0-9 ]", "", b.lower()).split())
    if not a_tokens or not b_tokens:
        return False
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    jaccard = len(intersection) / len(union)
    containment = len(intersection) / min(len(a_tokens), len(b_tokens))
    return jaccard >= threshold or containment >= threshold


# Source priority order — lower is "richer". When two records match, the one
# with the lower priority is kept (Overpass has structured tags, Playwright is
# unstructured HTML, DDG is just snippet text).
_SOURCE_PRIORITY = {"overpass": 0, "playwright": 1, "duckduckgo": 2}


def _merge_review_data(primary: ReviewData, secondary: ReviewData) -> ReviewData:
    """Merge sparse review metadata from duplicate source records."""
    sample_reviews = list(dict.fromkeys(primary.sample_reviews + secondary.sample_reviews))
    reviews = primary.reviews or secondary.reviews
    total_reviews = max(primary.total_reviews, secondary.total_reviews)
    average_rating = primary.average_rating if primary.average_rating is not None else secondary.average_rating
    positive = primary.positive_percentage or secondary.positive_percentage
    negative = primary.negative_percentage or secondary.negative_percentage
    themes = list(dict.fromkeys(primary.recurring_themes + secondary.recurring_themes))
    low_confidence = primary.low_confidence and secondary.low_confidence
    confidence_reason = primary.confidence_reason if primary.low_confidence else secondary.confidence_reason
    return ReviewData(
        total_reviews=total_reviews,
        average_rating=average_rating,
        positive_percentage=positive,
        negative_percentage=negative,
        recurring_themes=themes[:4],
        recency_score=primary.recency_score if primary.recency_score != 0.5 else secondary.recency_score,
        sample_reviews=sample_reviews[:5],
        reviews=reviews[:10],
        low_confidence=low_confidence,
        confidence_reason=confidence_reason,
    )


def _merge_listing(primary: BusinessListing, secondary: BusinessListing) -> BusinessListing:
    """Keep the preferred source row but fill missing fields from the duplicate."""
    updates: Dict[str, Any] = {
        "address": primary.address or secondary.address,
        "lat": primary.lat if primary.lat is not None else secondary.lat,
        "lng": primary.lng if primary.lng is not None else secondary.lng,
        "phone": primary.phone or secondary.phone,
        "website": primary.website or secondary.website,
        "opening_hours": primary.opening_hours or secondary.opening_hours,
        "maps_url": primary.maps_url or secondary.maps_url,
        "review_data": _merge_review_data(primary.review_data, secondary.review_data),
    }
    # Prefer a concrete Google Maps place URL over a generic search URL.
    if secondary.maps_url and "/maps/place/" in secondary.maps_url:
        updates["maps_url"] = secondary.maps_url
    return primary.model_copy(update=updates)


def _is_same_business(a: BusinessListing, b: BusinessListing) -> bool:
    """
    Treat two listings as the same business if:
      (1) their names fuzzy-match, OR
      (2) both have coordinates that are within 50 m of each other AND the
          names share at least one significant token.
    """
    from app.utils.geo import within_m

    if _fuzzy_similar(a.name, b.name):
        return True
    if within_m(a.lat, a.lng, b.lat, b.lng, threshold_m=50.0):
        # Require at least one shared meaningful token to avoid merging two
        # genuinely different businesses that happen to share an address.
        a_toks = set(re.sub(r"[^a-z0-9 ]", "", a.name.lower()).split())
        b_toks = set(re.sub(r"[^a-z0-9 ]", "", b.name.lower()).split())
        a_toks -= {"the", "and", "of", "a", "an"}
        b_toks -= {"the", "and", "of", "a", "an"}
        if a_toks & b_toks:
            return True
    return False


def _deduplicate(listings: List[BusinessListing]) -> List[BusinessListing]:
    """
    Remove near-duplicates using fuzzy name + coordinate proximity.

    When two listings refer to the same business, keep the one from the higher
    priority source (Overpass > Playwright > DuckDuckGo).
    """
    seen: List[BusinessListing] = []
    for listing in listings:
        duplicate = False
        for i, existing in enumerate(seen):
            if _is_same_business(listing, existing):
                lp = _SOURCE_PRIORITY.get(listing.source, 99)
                ep = _SOURCE_PRIORITY.get(existing.source, 99)
                if lp < ep:
                    seen[i] = _merge_listing(listing, existing)
                else:
                    seen[i] = _merge_listing(existing, listing)
                duplicate = True
                break
        if not duplicate:
            seen.append(listing)
    return seen


def _make_id(text: str) -> str:
    """Generate a short deterministic ID from arbitrary text."""
    return "ddg_" + hashlib.md5(text.encode()).hexdigest()[:12]


def _parse_count(text: str) -> int:
    """Parse compact review counts like '1,234' from Google text."""
    try:
        return int(re.sub(r"[^0-9]", "", text))
    except ValueError:
        return 0


def _extract_maps_rating_count(text: str) -> tuple[Optional[float], int]:
    """Extract rating and review count from Google Maps result text."""
    rating: Optional[float] = None
    count = 0
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
        count = _parse_count(count_match.group(1))
    return rating, count


async def _maybe_await(value: Any) -> Any:
    """Await coroutine-like values returned by test doubles."""
    if inspect.isawaitable(value):
        return await value
    return value


# ---------------------------------------------------------------------------
# Category auto-tagging (PDF §7.3)
# ---------------------------------------------------------------------------

# OSM-compatible tag vocabulary used for zero-shot classification.
_TAG_VOCAB = [
    "restaurant", "cafe", "bar", "pub", "fast_food",
    "dentist", "doctor", "clinic", "hospital", "pharmacy",
    "fitness_centre", "yoga_studio", "spa", "salon", "barber",
    "hotel", "motel",
    "supermarket", "convenience", "bakery", "butcher",
    "bank", "atm", "library", "school", "park",
    "coworking", "office",
    "tax_filing", "accountant", "lawyer", "real_estate",
    "fuel", "car_repair", "car_wash",
    "other",
]

_CATEGORY_TAG_TTL_S = 7 * 24 * 3600  # 7 days


def _auto_tag_cache_key(name: str, address: Optional[str]) -> str:
    """Stable cache key for the (name, first 30 chars of address) tuple."""
    raw = (name or "").lower().strip() + "|" + ((address or "")[:30].lower().strip())
    return "auto_tag:" + hashlib.md5(raw.encode()).hexdigest()


_tag_llm: Any = None
_tag_llm_checked = False


def _get_tag_llm() -> Optional[Any]:
    """Lazy LLM client for zero-shot classification. None if not configured."""
    global _tag_llm, _tag_llm_checked
    if _tag_llm_checked:
        return _tag_llm
    _tag_llm_checked = True
    settings = get_settings()
    try:
        if settings.LLM_PROVIDER == "groq" and settings.GROQ_API_KEY:
            from langchain_groq import ChatGroq  # type: ignore

            _tag_llm = ChatGroq(
                api_key=settings.GROQ_API_KEY, model_name=settings.LLM_MODEL
            )
        elif settings.LLM_PROVIDER == "ollama":
            from langchain_community.llms import Ollama  # type: ignore

            _tag_llm = Ollama(
                base_url=settings.OLLAMA_BASE_URL,
                model=settings.LLM_MODEL,
                temperature=0,
            )
    except Exception as exc:
        logger.warning("auto_tag_llm_init_failed", error=str(exc))
        _tag_llm = None
    return _tag_llm


def _auto_tag_category(
    name: str,
    snippet: Optional[str],
    address: Optional[str],
    cache: CacheManager,
) -> Optional[str]:
    """
    Zero-shot classify a business into an OSM-compatible tag.

    Returns one tag from _TAG_VOCAB on success, or None on failure / when no
    LLM is available. Results are cached for 7 days keyed by (name, address).
    """
    key = _auto_tag_cache_key(name, address)
    cached = cache.get(key)
    if cached:
        return str(cached)

    llm = _get_tag_llm()
    if llm is None:
        return None

    description = (snippet or "")[:300].replace("\n", " ")
    prompt = (
        "Classify this business into EXACTLY ONE of the following tags. "
        "Reply with the tag only, no other words.\n\n"
        f"Tags: {', '.join(_TAG_VOCAB)}\n\n"
        f"Business name: {name}\n"
        f"Address: {address or 'unknown'}\n"
        f"Description: {description or 'unknown'}\n\n"
        "Tag:"
    )
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        tag = text.strip().lower().split()[0] if text.strip() else ""
        tag = re.sub(r"[^a-z_]", "", tag)
        if tag in _TAG_VOCAB and tag != "other":
            cache.set(key, tag, ttl=_CATEGORY_TAG_TTL_S)
            return tag
    except Exception as exc:
        logger.warning("auto_tag_llm_error", error=str(exc), name=name)
    return None


class SearchAgent:
    """
    Multi-source business search agent.

    Uses Overpass API as the primary source, with DuckDuckGo as a fallback
    supplement.  Results are deduplicated and normalised.
    """

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(20.0)
        self._cache = CacheManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        intent: ParsedIntent,
        location: ResolvedLocation,
    ) -> List[BusinessListing]:
        """
        Execute a multi-source search and return deduplicated BusinessListings.

        Parameters
        ----------
        intent:
            Parsed user intent including category and desired count.
        location:
            Resolved location with bounding box.

        Returns
        -------
        List[BusinessListing]
            Up to ``intent.count * 2`` raw listings (before scoring/ranking).
        """
        osm_key, osm_value, extra_tags = _get_osm_tags(intent.category)
        logger.info(
            "search_start",
            category=intent.category,
            osm=f"{osm_key}={osm_value}",
            location=location.display_name,
        )

        # Sources run concurrently and are merged afterwards:
        # 1. Overpass/OpenStreetMap for structured geo data
        # 2. DuckDuckGo for web discovery/snippets
        # 3. Google Maps via Playwright for Maps-specific candidates
        import asyncio as _asyncio

        overpass_task = self._search_overpass(
            location, osm_key, osm_value, extra_tags, intent.count
        )
        ddg_task = self._search_duckduckgo(
            intent.category, location.display_name, intent.count
        )
        playwright_task = self._search_playwright(
            intent.category, location, intent.count
        )
        overpass_results, ddg_results, pw_results = await _asyncio.gather(
            overpass_task, ddg_task, playwright_task, return_exceptions=False
        )
        logger.info(
            "search_sources_done",
            overpass=len(overpass_results),
            ddg=len(ddg_results),
            playwright=len(pw_results),
        )

        combined = overpass_results + ddg_results + pw_results

        deduped = _deduplicate(combined)

        # PDF §7.3: zero-shot category auto-tagging for non-Overpass results
        # whose `category` is just the user's raw query string.
        for i, b in enumerate(deduped):
            if b.source == "overpass":
                continue  # OSM already has structured tags
            snippet = b.review_data.sample_reviews[0] if b.review_data.sample_reviews else None
            tag = _auto_tag_category(b.name, snippet, b.address, self._cache)
            if tag:
                deduped[i] = b.model_copy(update={"category": tag})

        logger.info("search_complete", raw=len(combined), deduped=len(deduped))
        return deduped

    # ------------------------------------------------------------------
    # Source 1 – Overpass API
    # ------------------------------------------------------------------

    async def _search_overpass(
        self,
        location: ResolvedLocation,
        osm_key: str,
        osm_value: str,
        extra_tags: Optional[Dict[str, str]],
        count: int,
    ) -> List[BusinessListing]:
        """Fetch businesses from the OpenStreetMap Overpass API."""
        query = _build_overpass_query(
            location.bounding_box, osm_key, osm_value, extra_tags
        )
        try:
            async with _overpass_limiter:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    headers = {
                        "Accept": "application/json",
                        "User-Agent": "LocalLens/1.0",
                    }
                    try:
                        # GET avoids Content-Type negotiation entirely (no body = no 406)
                        resp = await client.get(
                            _OVERPASS_URL,
                            params={"data": query},
                            headers=headers,
                        )
                        await _maybe_await(resp.raise_for_status())
                        data = await _maybe_await(resp.json())
                        if not isinstance(data, dict):
                            raise ValueError("Overpass GET returned non-JSON object")
                    except Exception:
                        # Some tests/proxies/Overpass mirrors expect POST-style form data.
                        resp = await client.post(
                            _OVERPASS_URL,
                            data={"data": query},
                            headers=headers,
                        )
                        await _maybe_await(resp.raise_for_status())
                        data = await _maybe_await(resp.json())

            elements = data.get("elements", [])
            listings: List[BusinessListing] = []
            for el in elements:
                listing = _osm_element_to_listing(el, category=osm_value)
                if listing:
                    listings.append(listing)
            return listings[: count * 3]

        except Exception as exc:
            logger.warning("overpass_search_error", error=str(exc))
            return []

    # ------------------------------------------------------------------
    # Source 2 – DuckDuckGo
    # ------------------------------------------------------------------

    async def _search_duckduckgo(
        self, category: str, location_name: str, count: int
    ) -> List[BusinessListing]:
        """Search DuckDuckGo for business names and parse the results."""
        try:
            from duckduckgo_search import DDGS  # type: ignore

            search_query = f"{category} in {location_name}"
            async with _ddg_limiter:
                # DDGS is synchronous; run in thread pool via executor if needed
                import asyncio

                loop = asyncio.get_event_loop()
                raw_results = await loop.run_in_executor(
                    None, self._ddg_sync_search, search_query, count * 3
                )

            listings: List[BusinessListing] = []
            for item in raw_results:
                title = item.get("title", "").strip()
                snippet = item.get("body", item.get("snippet", "")).strip()
                href = item.get("href", item.get("link", ""))

                if not title:
                    continue

                listings.append(
                    BusinessListing(
                        id=_make_id(title),
                        name=title,
                        address=None,
                        category=category,
                        source="duckduckgo",
                        website=href or None,
                        maps_url=_make_maps_url(title, None),
                        review_data=ReviewData(
                            sample_reviews=[snippet] if snippet else [],
                            low_confidence=True,
                            confidence_reason="DuckDuckGo snippet – limited review data",
                        ),
                    )
                )
            return listings

        except ImportError:
            logger.warning("duckduckgo_search_not_installed")
            return []
        except Exception as exc:
            logger.warning("duckduckgo_search_error", error=str(exc))
            return []

    @staticmethod
    def _ddg_sync_search(query: str, max_results: int) -> List[Dict[str, Any]]:
        """Synchronous DuckDuckGo search with backoff retry on rate limit."""
        import time
        from duckduckgo_search import DDGS  # type: ignore

        _BACKOFF = [5, 15, 30]  # seconds between attempts
        for attempt in range(3):
            try:
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results))
            except Exception as exc:
                err = str(exc)
                if ("202" in err or "Ratelimit" in err) and attempt < 2:
                    time.sleep(_BACKOFF[attempt])
                    continue
                return []  # give up gracefully after all retries
        return []

    # ------------------------------------------------------------------
    # Source 3 – Playwright fallback (PDF Module C tier 3)
    # ------------------------------------------------------------------

    async def _search_playwright(
        self,
        category: str,
        location: "ResolvedLocation",  # type: ignore[name-defined]
        count: int,
    ) -> List[BusinessListing]:
        """
        Scrape Google Maps search results as a last-resort fallback.

        Only invoked when Overpass + DuckDuckGo together didn't return enough
        results — this is the case for niche categories (e.g. "tax filing
        companies") that aren't covered by OSM amenity tags.
        """
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError:
            logger.info("playwright_not_installed_for_search")
            return []

        query_str = f"{category} near {location.display_name}"
        encoded = urllib.parse.quote(query_str)
        lat = location.coordinates.lat
        lng = location.coordinates.lng
        url = f"https://www.google.com/maps/search/{encoded}/@{lat},{lng},14z"

        listings: List[BusinessListing] = []
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
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2500)  # let result list mount
                    # Anchor tags inside the result feed have aria-label = business name
                    anchors = await page.query_selector_all(
                        'a[aria-label][href*="/maps/place/"]'
                    )
                    for a in anchors[: count * 3]:
                        name = (await a.get_attribute("aria-label") or "").strip()
                        href = await a.get_attribute("href") or ""
                        if not name:
                            continue
                        card_text = ""
                        try:
                            card_text = await a.evaluate(
                                """node => {
                                  const card = node.closest('div[role="article"]') || node.parentElement;
                                  return card ? card.innerText : '';
                                }"""
                            )
                        except Exception:
                            card_text = ""
                        rating, review_count = _extract_maps_rating_count(card_text)
                        listings.append(
                            BusinessListing(
                                id=_make_pw_id(name, href),
                                name=name,
                                address=None,
                                lat=None,
                                lng=None,
                                category=category,
                                source="playwright",
                                website=None,
                                maps_url=f"https://www.google.com{href}"
                                if href.startswith("/") else (href or _make_maps_url(name, None)),
                                review_data=ReviewData(
                                    total_reviews=review_count,
                                    average_rating=rating,
                                    sample_reviews=[],
                                    low_confidence=review_count < 5 or rating is None,
                                    confidence_reason=None
                                    if review_count >= 5 and rating is not None
                                    else "Discovered via Google Maps; limited rating/review metadata",
                                ),
                            )
                        )
                finally:
                    await context.close()
                    await browser.close()
        except Exception as exc:
            logger.warning("playwright_search_error", error=str(exc))
            return []
        return listings


def _make_pw_id(name: str, href: str) -> str:
    """Deterministic Playwright listing ID from name + href."""
    seed = (name + "|" + href).encode()
    return "pw_" + hashlib.md5(seed).hexdigest()[:12]
