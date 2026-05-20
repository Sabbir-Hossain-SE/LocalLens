"""
Tests for the location resolver module.

Uses httpx mock transport to avoid real network calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.location import ResolvedLocation
from app.modules.location_resolver import (
    LocationResolver,
    _compute_bounding_box,
    _default_location,
)


# ---------------------------------------------------------------------------
# Bounding box helper tests
# ---------------------------------------------------------------------------

class TestComputeBoundingBox:
    """Unit tests for the bounding box calculation."""

    def test_bbox_has_expected_shape(self):
        bbox = _compute_bounding_box(lat=40.7128, lng=-74.0060, radius_km=5.0)
        assert bbox.north > bbox.south
        assert bbox.east > bbox.west

    def test_bbox_south_north_span(self):
        """At mid-latitudes, 5 km radius ≈ 0.045° latitude span each side."""
        bbox = _compute_bounding_box(lat=40.0, lng=-74.0, radius_km=5.0)
        delta_lat = bbox.north - bbox.south
        # 2 * (5/111) ≈ 0.09
        assert 0.08 < delta_lat < 0.10

    def test_larger_radius_produces_wider_box(self):
        small = _compute_bounding_box(lat=51.5, lng=-0.12, radius_km=1.0)
        large = _compute_bounding_box(lat=51.5, lng=-0.12, radius_km=20.0)
        assert (large.north - large.south) > (small.north - small.south)
        assert (large.east - large.west) > (small.east - small.west)

    def test_returns_bounding_box_model(self):
        from app.models.location import BoundingBox
        bbox = _compute_bounding_box(0.0, 0.0, 5.0)
        assert isinstance(bbox, BoundingBox)


class TestDefaultLocation:
    """Unit tests for the hardcoded default location fallback."""

    def test_returns_resolved_location(self):
        loc = _default_location()
        assert isinstance(loc, ResolvedLocation)

    def test_default_type_is_default(self):
        loc = _default_location()
        assert loc.location_type == "default"

    def test_has_valid_bounding_box(self):
        loc = _default_location(radius_km=5.0)
        assert loc.bounding_box.north > loc.bounding_box.south


# ---------------------------------------------------------------------------
# LocationResolver integration tests (network calls mocked)
# ---------------------------------------------------------------------------

class TestLocationResolver:
    """Integration tests for LocationResolver with mocked HTTP calls."""

    @pytest.fixture
    def resolver(self):
        r = LocationResolver()
        # Disable cache to prevent state leakage between tests
        r._cache = MagicMock()
        r._cache.get.return_value = None
        r._cache.set.return_value = True
        return r

    @pytest.mark.asyncio
    async def test_near_me_with_localhost_ip_returns_default(self, resolver):
        """Localhost IP should bypass ip-api and return the default location."""
        loc = await resolver.resolve("near_me", radius_km=5.0, user_ip="127.0.0.1")
        assert loc.location_type == "default"

    @pytest.mark.asyncio
    async def test_near_me_with_no_ip_returns_default(self, resolver):
        """Missing IP should return the default location."""
        loc = await resolver.resolve("near_me", radius_km=5.0, user_ip=None)
        assert loc.location_type == "default"

    @pytest.mark.asyncio
    async def test_near_me_real_ip_calls_ip_api(self, resolver):
        """Valid-looking IP should call ip-api and use its response."""
        ip_api_response = {
            "status": "success",
            "lat": 47.6062,
            "lon": -122.3321,
            "city": "Seattle",
            "regionName": "Washington",
        }

        async def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = ip_api_response
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client_cls.return_value = mock_client

            loc = await resolver.resolve("near_me", radius_km=5.0, user_ip="203.0.113.1")

        assert "Seattle" in loc.display_name
        assert abs(loc.coordinates.lat - 47.6062) < 0.01
        assert loc.location_type == "ip_geolocation"

    @pytest.mark.asyncio
    async def test_zip_code_resolution(self, resolver):
        """5-digit ZIP code should trigger postalcode Nominatim search."""
        nominatim_response = [
            {
                "lat": "40.6892",
                "lon": "-74.0445",
                "display_name": "Brooklyn, New York, 11201, United States",
                "type": "postal_code",
            }
        ]

        async def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = nominatim_response
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client_cls.return_value = mock_client

            loc = await resolver.resolve("11201", radius_km=5.0)

        assert loc.location_type == "zip_code"
        assert abs(loc.coordinates.lat - 40.6892) < 0.01

    @pytest.mark.asyncio
    async def test_city_name_resolution(self, resolver):
        """Plain city name should use Nominatim free-text search."""
        nominatim_response = [
            {
                "lat": "41.8781",
                "lon": "-87.6298",
                "display_name": "Chicago, Cook County, Illinois, United States",
                "type": "city",
            }
        ]

        async def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = nominatim_response
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client_cls.return_value = mock_client

            loc = await resolver.resolve("Chicago, IL", radius_km=5.0)

        assert "Chicago" in loc.display_name
        assert abs(loc.coordinates.lat - 41.8781) < 0.01
        assert abs(loc.coordinates.lng - (-87.6298)) < 0.01

    @pytest.mark.asyncio
    async def test_nominatim_failure_falls_back_to_default(self, resolver):
        """When Nominatim returns an empty list, fall back to the default location."""
        async def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = []
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=mock_get)
            mock_client_cls.return_value = mock_client

            loc = await resolver.resolve("NonExistentCityXYZ", radius_km=5.0)

        assert loc.location_type == "default"

    @pytest.mark.asyncio
    async def test_network_error_falls_back_to_default(self, resolver):
        """Network errors should be caught and the default location returned."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=ConnectionError("Network unreachable"))
            mock_client_cls.return_value = mock_client

            loc = await resolver.resolve("Seattle", radius_km=5.0)

        assert loc.location_type == "default"
