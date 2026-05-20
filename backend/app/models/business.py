"""
Pydantic models representing a business listing and its aggregated review data.

BusinessListing is the primary data structure that flows through the pipeline
from the search agent all the way to the response formatter.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ReviewData(BaseModel):
    """Aggregated review and sentiment data for a single business."""

    total_reviews: int = Field(default=0, ge=0, description="Total number of reviews found")
    average_rating: Optional[float] = Field(
        default=None, ge=0.0, le=5.0, description="Mean star rating (0-5)"
    )
    positive_percentage: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Percentage of positive-sentiment reviews"
    )
    negative_percentage: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Percentage of negative-sentiment reviews"
    )
    recurring_themes: List[str] = Field(
        default_factory=list,
        description="Most-mentioned topics / adjectives extracted from review text",
    )
    recency_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Normalised recency signal (0=old, 1=very recent)",
    )
    sample_reviews: List[str] = Field(
        default_factory=list, description="Up to 5 representative review snippets"
    )
    low_confidence: bool = Field(
        default=False,
        description="True if the review data is sparse or unreliable",
    )
    confidence_reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of why confidence is low",
    )


class BusinessListing(BaseModel):
    """A single business listing enriched with reviews, scoring, and a summary."""

    id: str = Field(description="Unique identifier (OSM node ID, hash, etc.)")
    name: str = Field(description="Business name")
    address: Optional[str] = Field(default=None, description="Street address or full address")
    lat: Optional[float] = Field(default=None, description="Latitude of the business")
    lng: Optional[float] = Field(default=None, description="Longitude of the business")
    category: str = Field(description="Business category / type")
    phone: Optional[str] = Field(default=None, description="Phone number")
    website: Optional[str] = Field(default=None, description="Website URL")
    opening_hours: Optional[str] = Field(
        default=None, description="Opening hours in OSM format or plain text"
    )
    source: str = Field(
        description="Data source: 'overpass', 'duckduckgo', or 'playwright'"
    )
    review_data: ReviewData = Field(
        default_factory=ReviewData,
        description="Aggregated review and sentiment data",
    )
    composite_score: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Weighted composite quality score (0-100)"
    )
    rank: int = Field(default=0, ge=0, description="1-based rank in the final results list")
    summary: Optional[str] = Field(
        default=None, description="LLM-generated or template-based 2-3 sentence summary"
    )
    maps_url: Optional[str] = Field(
        default=None, description="Google Maps search URL for the business"
    )
