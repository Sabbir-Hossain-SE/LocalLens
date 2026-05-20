"""
Module B – Location Resolver.

Converts a location string (city name, zip code, or "near_me") into a
ResolvedLocation with precise coordinates and a bounding box.

Resolution strategy:
  1. "near_me"  → IP geolocation via ip-api.com
  2. 5-digit zip → Nominatim postalcode search
  3. Anything else → Nominatim free-text geocoding
  4. All paths fall back to the configurable default location (NYC).
"""

from __future__ import annotations

import math
import re
from typing import Optional, Tuple

import httpx

from app.config import get_settings
from app.models.location import BoundingBox, Coordinates, ResolvedLocation
from app.utils.cache import CacheManager
from app.utils.logger import get_logger
from app.utils.rate_limiter import MultiRateLimiter

logger = get_logger(__name__)

_NOMINATIM_USER_AGENT = "LocalLens/1.0 (contact@locallens.dev)"
_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_IP_API_BASE = "http://ip-api.com/json"

# Nominatim ToS: max 1 request/second
_nominatim_limiter = MultiRateLimiter.get("nominatim", calls_per_second=1.0)
_ip_api_limiter = MultiRateLimiter.get("ip_api", calls_per_second=2.0)


def _compute_bounding_box(lat: float, lng: float, radius_km: float) -> BoundingBox:
    """
    Compute a square bounding box centred on (lat, lng) with the given radius.

    Uses the approximation: 1° latitude ≈ 111 km, and compensates for
    longitude compression at higher latitudes.
    """
    lat_rad = math.radians(lat)
    radius_deg_lat = radius_km / 111.0
    radius_deg_lng = radius_km / (111.0 * math.cos(lat_rad)) if math.cos(lat_rad) != 0 else radius_deg_lat

    return BoundingBox(
        south=lat - radius_deg_lat,
        north=lat + radius_deg_lat,
        west=lng - radius_deg_lng,
        east=lng + radius_deg_lng,
    )


def _default_location(radius_km: float = 5.0) -> ResolvedLocation:
    """Return the hardcoded default location (configurable via .env)."""
    settings = get_settings()
    lat = settings.DEFAULT_LOCATION_LAT
    lng = settings.DEFAULT_LOCATION_LNG
    return ResolvedLocation(
        display_name=settings.DEFAULT_LOCATION_NAME,
        coordinates=Coordinates(lat=lat, lng=lng),
        bounding_box=_compute_bounding_box(lat, lng, radius_km),
        location_type="default",
    )


class LocationResolver:
    """
    Resolves location strings to geographic coordinates and bounding boxes.

    Results are cached in diskcache to avoid redundant geocoding calls.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._cache = CacheManager()
        self._client_timeout = httpx.Timeout(10.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(
        self,
        location: str,
        radius_km: float = 5.0,
        user_ip: Optional[str] = None,
    ) -> ResolvedLocation:
        """
        Resolve a location string to a ResolvedLocation.

        Parameters
        ----------
        location:
            Raw location string from ParsedIntent.  May be ``"near_me"``,
            a five-digit ZIP code, or a city/neighbourhood name.
        radius_km:
            Used to compute the bounding box around the resolved point.
        user_ip:
            Caller's IP address – only used when location == "near_me".

        Returns
        -------
        ResolvedLocation
            Coordinates + bounding box for the search area.
        """
        cache_key = f"loc:{location.lower().strip()}:{radius_km}"
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug("location_cache_hit", location=location)
            return ResolvedLocation(**cached) if isinstance(cached, dict) else cached

        resolved = await self._resolve_uncached(location, radius_km, user_ip)

        # Store as dict for reliable diskcache serialisation
        self._cache.set(cache_key, resolved.model_dump(), ttl=self._settings.CACHE_TTL_SECONDS)
        return resolved

    # ------------------------------------------------------------------
    # Internal resolution strategies
    # ------------------------------------------------------------------

    async def _resolve_uncached(
        self, location: str, radius_km: float, user_ip: Optional[str]
    ) -> ResolvedLocation:
        """Dispatch to the appropriate resolution strategy."""
        loc = location.strip().lower()

        if loc in ("near_me", "nearby", "near me", "close to me"):
            return await self._resolve_by_ip(user_ip, radius_km)

        if re.fullmatch(r"\d{5}", loc):
            return await self._resolve_zip(location.strip(), radius_km)

        return await self._resolve_nominatim(location.strip(), radius_km)

    async def _resolve_by_ip(
        self, user_ip: Optional[str], radius_km: float
    ) -> ResolvedLocation:
        """Geolocate using ip-api.com (no API key required)."""
        # Localhost / private IPs cannot be geolocated
        if not user_ip or user_ip in ("127.0.0.1", "::1", "localhost"):
            logger.info("location_ip_private_fallback")
            return _default_location(radius_km)

        url = f"{_IP_API_BASE}/{user_ip}"
        try:
            async with _ip_api_limiter:
                async with httpx.AsyncClient(timeout=self._client_timeout) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()

            if data.get("status") != "success":
                logger.warning("ip_api_failed", ip=user_ip, message=data.get("message"))
                return _default_location(radius_km)

            lat = float(data["lat"])
            lng = float(data["lon"])
            city = data.get("city", "")
            region = data.get("regionName", "")
            display = f"{city}, {region}".strip(", ")
            logger.info("location_resolved_ip", ip=user_ip, display=display)

            return ResolvedLocation(
                display_name=display or "Current Location",
                coordinates=Coordinates(lat=lat, lng=lng),
                bounding_box=_compute_bounding_box(lat, lng, radius_km),
                location_type="ip_geolocation",
            )
        except Exception as exc:
            logger.warning("ip_geolocation_error", error=str(exc), ip=user_ip)
            return _default_location(radius_km)

    async def _resolve_zip(self, zip_code: str, radius_km: float) -> ResolvedLocation:
        """Geocode a US ZIP code using Nominatim's postalcode parameter."""
        params = {
            "postalcode": zip_code,
            "countrycodes": "us",
            "format": "json",
            "limit": 1,
        }
        result = await self._nominatim_search(params)
        if result:
            lat = float(result["lat"])
            lng = float(result["lon"])
            display = result.get("display_name", zip_code)
            logger.info("location_resolved_zip", zip=zip_code, display=display[:40])
            return ResolvedLocation(
                display_name=display,
                coordinates=Coordinates(lat=lat, lng=lng),
                bounding_box=_compute_bounding_box(lat, lng, radius_km),
                location_type="zip_code",
            )
        logger.warning("zip_resolution_failed", zip=zip_code)
        return _default_location(radius_km)

    async def _resolve_nominatim(self, location: str, radius_km: float) -> ResolvedLocation:
        """Free-text geocode a city/neighbourhood using Nominatim."""
        params = {"q": location, "format": "json", "limit": 1, "addressdetails": 1}
        result = await self._nominatim_search(params)
        if result:
            lat = float(result["lat"])
            lng = float(result["lon"])
            display = result.get("display_name", location)
            loc_class = result.get("type", "city_name")
            logger.info("location_resolved_nominatim", query=location, display=display[:50])
            return ResolvedLocation(
                display_name=display,
                coordinates=Coordinates(lat=lat, lng=lng),
                bounding_box=_compute_bounding_box(lat, lng, radius_km),
                location_type=loc_class,
            )
        logger.warning("nominatim_resolution_failed", location=location)
        return _default_location(radius_km)

    async def _nominatim_search(self, params: dict) -> Optional[dict]:
        """
        Make a single request to the Nominatim search endpoint.

        Respects the 1 req/s rate limit and returns the first result or None.
        """
        url = f"{_NOMINATIM_BASE}/search"
        headers = {"User-Agent": _NOMINATIM_USER_AGENT}
        try:
            async with _nominatim_limiter:
                async with httpx.AsyncClient(timeout=self._client_timeout) as client:
                    resp = await client.get(url, params=params, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
            return data[0] if data else None
        except Exception as exc:
            logger.warning("nominatim_request_error", error=str(exc))
            return None
