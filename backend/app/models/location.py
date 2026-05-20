"""
Pydantic models representing a resolved geographic location.

The location resolver converts a raw string (city name, zip code, "near me")
into a concrete set of coordinates and a bounding box used by the search agent.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    """A latitude/longitude point on the Earth's surface."""

    lat: float = Field(description="Latitude in decimal degrees (-90 to 90)")
    lng: float = Field(description="Longitude in decimal degrees (-180 to 180)")


class BoundingBox(BaseModel):
    """A rectangular geographic bounding box."""

    south: float = Field(description="Southern edge latitude")
    west: float = Field(description="Western edge longitude")
    north: float = Field(description="Northern edge latitude")
    east: float = Field(description="Eastern edge longitude")


class ResolvedLocation(BaseModel):
    """The fully resolved geographic context for a search."""

    display_name: str = Field(description="Human-readable location name")
    coordinates: Coordinates = Field(description="Central coordinates of the search area")
    bounding_box: BoundingBox = Field(description="Rectangular search area")
    location_type: str = Field(
        description=(
            "How the location was resolved: "
            "'ip_geolocation', 'city_name', 'zip_code', 'neighborhood', or 'default'"
        )
    )
