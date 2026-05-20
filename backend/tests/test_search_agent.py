"""
Tests for the search agent module.

Validates category-to-OSM-tag mapping, Overpass result normalisation,
and the deduplication logic.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.business import BusinessListing
from app.models.intent import ParsedIntent, SearchFilters
from app.models.location import BoundingBox, Coordinates, ResolvedLocation
from app.modules.search_agent import (
    SearchAgent,
    _build_overpass_query,
    _deduplicate,
    _fuzzy_similar,
    _get_osm_tags,
    _make_maps_url,
    _osm_element_to_listing,
)


# ---------------------------------------------------------------------------
# Category → OSM tag mapping
# ---------------------------------------------------------------------------

class TestGetOsmTags:
    """Unit tests for _get_osm_tags category lookup."""

    def test_restaurant(self):
        key, val, extra = _get_osm_tags("restaurant")
        assert key == "amenity"
        assert val == "restaurant"

    def test_sushi_exact(self):
        key, val, extra = _get_osm_tags("sushi")
        assert val == "restaurant"
        assert extra is not None
        assert extra.get("cuisine") == "sushi"

    def test_sushi_restaurant_phrase(self):
        key, val, extra = _get_osm_tags("sushi restaurant")
        assert extra is not None and extra.get("cuisine") == "sushi"

    def test_cafe(self):
        key, val, _ = _get_osm_tags("cafe")
        assert key == "amenity"
        assert val == "cafe"

    def test_coffee(self):
        key, val, _ = _get_osm_tags("coffee")
        assert val == "cafe"

    def test_bar(self):
        key, val, _ = _get_osm_tags("bar")
        assert val == "bar"

    def test_dentist(self):
        key, val, _ = _get_osm_tags("dentist")
        assert val == "dentist"

    def test_gym(self):
        key, val, _ = _get_osm_tags("gym")
        assert key == "leisure"
        assert val == "fitness_centre"

    def test_yoga(self):
        key, val, extra = _get_osm_tags("yoga")
        assert val == "fitness_centre"
        assert extra is not None and extra.get("sport") == "yoga"

    def test_pharmacy(self):
        key, val, _ = _get_osm_tags("pharmacy")
        assert val == "pharmacy"

    def test_hotel(self):
        key, val, _ = _get_osm_tags("hotel")
        assert key == "tourism"
        assert val == "hotel"

    def test_supermarket(self):
        key, val, _ = _get_osm_tags("supermarket")
        assert key == "shop"
        assert val == "supermarket"

    def test_coworking(self):
        key, val, _ = _get_osm_tags("coworking")
        assert key == "office"
        assert val == "coworking"

    def test_park(self):
        key, val, _ = _get_osm_tags("park")
        assert key == "leisure"
        assert val == "park"

    def test_unknown_falls_back_to_restaurant(self):
        """Unknown categories should fall back to amenity=restaurant."""
        key, val, _ = _get_osm_tags("some_unknown_category_xyz")
        assert key == "amenity"
        assert val == "restaurant"

    def test_partial_word_match(self):
        """'coffee shop' should match 'coffee' key."""
        key, val, _ = _get_osm_tags("coffee shop")
        assert val == "cafe"


# ---------------------------------------------------------------------------
# OSM element normalisation
# ---------------------------------------------------------------------------

class TestOsmElementToListing:
    """Unit tests for _osm_element_to_listing."""

    def _make_node(self, node_id=1, name="Test Cafe", lat=47.6, lon=-122.3, tags=None):
        base_tags = {"name": name, "amenity": "cafe"}
        if tags:
            base_tags.update(tags)
        return {"type": "node", "id": node_id, "lat": lat, "lon": lon, "tags": base_tags}

    def test_named_node_becomes_listing(self):
        node = self._make_node()
        listing = _osm_element_to_listing(node, "cafe")
        assert listing is not None
        assert listing.name == "Test Cafe"
        assert listing.source == "overpass"

    def test_unnamed_node_returns_none(self):
        node = self._make_node(name="")
        node["tags"].pop("name", None)
        listing = _osm_element_to_listing(node, "cafe")
        assert listing is None

    def test_coordinates_extracted_from_node(self):
        node = self._make_node(lat=47.6062, lon=-122.3321)
        listing = _osm_element_to_listing(node, "cafe")
        assert listing is not None
        assert abs(listing.lat - 47.6062) < 0.001
        assert abs(listing.lng - (-122.3321)) < 0.001

    def test_way_uses_center_coordinates(self):
        way = {
            "type": "way",
            "id": 42,
            "center": {"lat": 51.5, "lon": -0.12},
            "tags": {"name": "Hyde Park Coffee", "amenity": "cafe"},
        }
        listing = _osm_element_to_listing(way, "cafe")
        assert listing is not None
        assert abs(listing.lat - 51.5) < 0.001

    def test_address_assembled_from_tags(self):
        node = self._make_node(tags={
            "addr:housenumber": "123",
            "addr:street": "Main St",
            "addr:city": "Portland",
        })
        listing = _osm_element_to_listing(node, "cafe")
        assert listing.address is not None
        assert "123" in listing.address
        assert "Main St" in listing.address

    def test_phone_and_website_extracted(self):
        node = self._make_node(tags={
            "phone": "+1 206 555 0199",
            "website": "https://testcafe.example.com",
        })
        listing = _osm_element_to_listing(node, "cafe")
        assert listing.phone == "+1 206 555 0199"
        assert listing.website == "https://testcafe.example.com"

    def test_id_has_osm_prefix(self):
        node = self._make_node(node_id=99999)
        listing = _osm_element_to_listing(node, "cafe")
        assert listing.id.startswith("osm_")

    def test_maps_url_generated(self):
        node = self._make_node(name="Blue Bottle Coffee")
        listing = _osm_element_to_listing(node, "cafe")
        assert listing.maps_url is not None
        assert "google.com/maps" in listing.maps_url


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplicate:
    """Tests for the fuzzy-deduplication logic."""

    def _listing(self, name: str, source: str = "overpass") -> BusinessListing:
        return BusinessListing(id=name, name=name, category="cafe", source=source)

    def test_exact_duplicates_removed(self):
        listings = [
            self._listing("Joe's Pizza"),
            self._listing("Joe's Pizza"),
        ]
        deduped = _deduplicate(listings)
        assert len(deduped) == 1

    def test_similar_names_deduplicated(self):
        listings = [
            self._listing("Joe's Pizza Restaurant"),
            self._listing("Joe's Pizza"),
        ]
        deduped = _deduplicate(listings)
        assert len(deduped) == 1

    def test_different_names_kept(self):
        listings = [
            self._listing("Blue Bottle Coffee"),
            self._listing("Starbucks"),
            self._listing("Peets Coffee"),
        ]
        deduped = _deduplicate(listings)
        assert len(deduped) == 3

    def test_overpass_preferred_over_duckduckgo(self):
        """When OSM and DDG have the same business, keep OSM version."""
        osm = self._listing("Joe's Pizza", source="overpass")
        ddg = self._listing("Joe's Pizza", source="duckduckgo")
        deduped = _deduplicate([ddg, osm])
        assert len(deduped) == 1
        assert deduped[0].source == "overpass"


# ---------------------------------------------------------------------------
# Overpass query builder
# ---------------------------------------------------------------------------

class TestBuildOverpassQuery:
    """Tests for the Overpass QL query construction."""

    def _bbox(self):
        return BoundingBox(south=47.5, west=-122.4, north=47.7, east=-122.2)

    def test_query_contains_osm_key_value(self):
        q = _build_overpass_query(self._bbox(), "amenity", "restaurant", None)
        assert '"amenity"="restaurant"' in q

    def test_query_contains_bbox(self):
        q = _build_overpass_query(self._bbox(), "amenity", "cafe", None)
        assert "47.5,-122.4,47.7,-122.2" in q

    def test_extra_tags_included(self):
        q = _build_overpass_query(self._bbox(), "amenity", "restaurant", {"cuisine": "sushi"})
        assert '"cuisine"="sushi"' in q

    def test_no_extra_tags_produces_cleaner_query(self):
        q = _build_overpass_query(self._bbox(), "amenity", "cafe", None)
        assert '"cuisine"' not in q

    def test_query_includes_timeout(self):
        q = _build_overpass_query(self._bbox(), "amenity", "cafe", None, timeout=20)
        assert "timeout:20" in q


# ---------------------------------------------------------------------------
# SearchAgent integration (network mocked)
# ---------------------------------------------------------------------------

class TestSearchAgent:
    """Integration tests for SearchAgent with mocked HTTP and DDG calls."""

    def _make_intent(self, category="cafe", count=5) -> ParsedIntent:
        return ParsedIntent(
            category=category,
            count=count,
            location="near_me",
            raw_query=f"best {category} near me",
        )

    def _make_location(self) -> ResolvedLocation:
        return ResolvedLocation(
            display_name="Seattle, WA",
            coordinates=Coordinates(lat=47.6, lng=-122.33),
            bounding_box=BoundingBox(south=47.55, west=-122.38, north=47.65, east=-122.28),
            location_type="ip_geolocation",
        )

    @pytest.mark.asyncio
    async def test_search_returns_list(self):
        """search() must return a list (may be empty if mocked as empty)."""
        agent = SearchAgent()
        overpass_response = {"elements": []}
        ddg_results: list = []

        async def mock_post(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = overpass_response
            return resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_cls.return_value = mock_client

            with patch.object(agent, "_search_duckduckgo", return_value=ddg_results):
                results = await agent.search(self._make_intent(), self._make_location())

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_overpass_results_normalised(self):
        """Overpass elements should be normalised to BusinessListings."""
        agent = SearchAgent()
        overpass_response = {
            "elements": [
                {
                    "type": "node",
                    "id": 1001,
                    "lat": 47.61,
                    "lon": -122.33,
                    "tags": {"name": "Green Bean Cafe", "amenity": "cafe"},
                }
            ]
        }

        async def mock_post(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = overpass_response
            return resp

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_cls.return_value = mock_client

            with patch.object(agent, "_search_duckduckgo", return_value=[]):
                results = await agent.search(self._make_intent(), self._make_location())

        assert len(results) >= 1
        assert results[0].name == "Green Bean Cafe"
        assert results[0].source == "overpass"

    @pytest.mark.asyncio
    async def test_overpass_error_returns_empty_not_raise(self):
        """Overpass HTTP errors should be caught, not propagate."""
        agent = SearchAgent()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=Exception("Overpass timeout"))
            mock_cls.return_value = mock_client

            with patch.object(agent, "_search_duckduckgo", return_value=[]):
                results = await agent.search(self._make_intent(), self._make_location())

        assert isinstance(results, list)
