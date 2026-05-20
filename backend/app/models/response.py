"""
Pydantic models for the API response layer.

SearchResponse is returned from the POST /search endpoint.
StreamEvent is yielded one-at-a-time from the SSE /search/stream endpoint.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from .business import BusinessListing


class SearchResponse(BaseModel):
    """Full response payload returned after the pipeline completes."""

    query: str = Field(description="Original user query")
    location: str = Field(description="Resolved location display name")
    total_results: int = Field(description="Number of results in the response")
    results: List[BusinessListing] = Field(description="Ranked list of business listings")
    elapsed_ms: int = Field(description="Total pipeline execution time in milliseconds")
    pipeline_steps: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Metadata from each pipeline stage for debugging / transparency",
    )


class StreamEvent(BaseModel):
    """A single Server-Sent Event emitted during streaming pipeline execution."""

    event: str = Field(
        description=(
            "Stage identifier: 'intent_parsed' | 'location_resolved' | 'search_complete' | "
            "'reviews_aggregated' | 'scoring_complete' | 'summary_ready' | 'done' | 'error'"
        )
    )
    data: Dict[str, Any] = Field(description="Stage-specific payload")
    step: int = Field(description="0-based index of this step in the pipeline")
    total_steps: int = Field(default=7, description="Total number of pipeline steps")
