"""
Module G – Response Formatter.

Takes the fully processed list of ranked, summarised BusinessListings and
packages them into a SearchResponse ready for the API layer.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from app.models.business import BusinessListing
from app.models.intent import ParsedIntent
from app.models.location import ResolvedLocation
from app.models.response import SearchResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ResponseFormatter:
    """
    Assembles the final SearchResponse from pipeline outputs.

    Tracks elapsed time and records per-stage metadata in pipeline_steps
    so callers can inspect timing and data quality information.
    """

    def format(
        self,
        query: str,
        intent: ParsedIntent,
        location: ResolvedLocation,
        listings: List[BusinessListing],
        pipeline_steps: List[Dict[str, Any]],
        start_time: float,
    ) -> SearchResponse:
        """
        Build and return a SearchResponse.

        Parameters
        ----------
        query:
            Original raw query string.
        intent:
            Parsed intent – used for the response's location field.
        location:
            Resolved location.
        listings:
            Final ranked, scored, and summarised listings.
        pipeline_steps:
            List of step-metadata dicts accumulated during the pipeline run.
        start_time:
            ``time.monotonic()`` timestamp recorded at the start of the pipeline.

        Returns
        -------
        SearchResponse
            Ready-to-serialise API response.
        """
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "response_formatted",
            results=len(listings),
            elapsed_ms=elapsed_ms,
        )

        return SearchResponse(
            query=query,
            location=location.display_name,
            total_results=len(listings),
            results=listings,
            elapsed_ms=elapsed_ms,
            pipeline_steps=pipeline_steps,
        )
