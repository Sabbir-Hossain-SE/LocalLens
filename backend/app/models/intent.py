"""
Pydantic models representing a parsed user intent.

These models carry the structured output of the intent parser module
and flow through the rest of the pipeline.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SearchFilters(BaseModel):
    """Optional search filters extracted from the user query."""

    open_now: bool = Field(default=False, description="Only show places currently open")
    min_rating: Optional[float] = Field(
        default=None, ge=0.0, le=5.0, description="Minimum star rating (0-5)"
    )
    price_level: Optional[str] = Field(
        default=None,
        description="Price tier: 'affordable', 'moderate', or 'expensive'",
    )
    max_distance_km: Optional[float] = Field(
        default=None, gt=0, description="Maximum distance in kilometres"
    )

    @field_validator("price_level", mode="before")
    @classmethod
    def validate_price_level(cls, v: object) -> Optional[str]:
        """Normalise and validate the price_level string."""
        if v is None:
            return None
        allowed = {"affordable", "moderate", "expensive"}
        v_str = str(v).lower().strip()
        if v_str not in allowed:
            return None  # Silently drop unknown values instead of raising
        return v_str


class ParsedIntent(BaseModel):
    """Fully structured representation of what the user is searching for."""

    category: str = Field(description="Type of business or service requested")
    count: int = Field(default=5, ge=1, le=50, description="Number of results to return")
    location: str = Field(
        description="Location string as-is from the query, or 'near_me' for proximity search"
    )
    radius_km: float = Field(default=5.0, gt=0, description="Search radius in kilometres")
    sort_by: str = Field(
        default="rating",
        description="Primary sort criterion: 'rating', 'distance', or 'reviews'",
    )
    filters: SearchFilters = Field(
        default_factory=SearchFilters, description="Additional search filters"
    )
    raw_query: str = Field(description="Original unmodified query string from the user")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="LLM confidence in the parsed intent (0-1)",
    )

    @field_validator("sort_by", mode="before")
    @classmethod
    def validate_sort_by(cls, v: object) -> str:
        """Normalise the sort_by field and fall back to 'rating' for unknown values."""
        allowed = {"rating", "distance", "reviews"}
        v_str = str(v).lower().strip()
        return v_str if v_str in allowed else "rating"
