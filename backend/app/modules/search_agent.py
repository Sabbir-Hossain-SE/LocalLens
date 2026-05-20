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
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.models.business import BusinessListing, ReviewData
from app.models.intent import ParsedIntent
from app.models.location import ResolvedLocation
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
        f'[out:json][timeout:{timeout}];'
        f'('
        f'  node["{osm_key}"="{osm_value}"]{extra}({bbox_str});'
        f'  way["{osm_key}"="{osm_value}"]{extra}({bbox_str});'
        f');'
        f'out center;'
    )
    return query


def _osm_element_to_listing(element: Dict[str, Any], category: str) -> Optional[BusinessListing]:
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
    """Generate a Google Maps search URL for a business."""
    query_parts = [name]
    if address:
        query_parts.append(address)
    query = "+".join(urllib.parse.quote(p) for p in query_parts)
    return f"https://www.google.com/maps/search/{query}"


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
    return (len(intersection) / len(union)) >= threshold


def _deduplicate(listings: List[BusinessListing]) -> List[BusinessListing]:
    """Remove near-duplicate listings, keeping the one from the richer source."""
    seen: List[BusinessListing] = []
    for listing in listings:
        duplicate = False
        for existing in seen:
            if _fuzzy_similar(listing.name, existing.name):
                # Keep the Overpass record over a DuckDuckGo record
                if listing.source == "overpass" and existing.source != "overpass":
                    seen.remove(existing)
                    seen.append(listing)
                duplicate = True
                break
        if not duplicate:
            seen.append(listing)
    return seen


def _make_id(text: str) -> str:
    """Generate a short deterministic ID from arbitrary text."""
    return "ddg_" + hashlib.md5(text.encode()).hexdigest()[:12]


class SearchAgent:
    """
    Multi-source business search agent.

    Uses Overpass API as the primary source, with DuckDuckGo as a fallback
    supplement.  Results are deduplicated and normalised.
    """

    def __init__(self) -> None:
        self._timeout = httpx.Timeout(20.0)

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

        # Source 1 – Overpass
        overpass_results = await self._search_overpass(
            location, osm_key, osm_value, extra_tags, intent.count
        )
        logger.info("overpass_results", count=len(overpass_results))

        # Source 2 – DuckDuckGo (always run to supplement)
        ddg_results = await self._search_duckduckgo(
            intent.category, location.display_name, intent.count
        )
        logger.info("ddg_results", count=len(ddg_results))

        combined = overpass_results + ddg_results
        deduped = _deduplicate(combined)

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
                    resp = await client.post(
                        _OVERPASS_URL,
                        data={"data": query},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    resp.raise_for_status()
                    data = resp.json()

            elements = data.get("elements", [])
            listings: List[BusinessListing] = []
            for el in elements:
                listing = _osm_element_to_listing(el, category=osm_value)
                if listing:
                    listings.append(listing)
            return listings[: count * 3]  # Return more than needed for scoring

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
        """Synchronous DuckDuckGo search call (run in executor)."""
        from duckduckgo_search import DDGS  # type: ignore

        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
