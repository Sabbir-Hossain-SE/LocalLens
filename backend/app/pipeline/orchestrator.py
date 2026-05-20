"""
Pipeline Orchestrator.

Chains all seven processing modules together and exposes an async generator
``run_pipeline`` that yields StreamEvents as each step completes.

Pipeline stages (step indices 0-6):
  0 – Intent Parser
  1 – Location Resolver
  2 – Search Agent
  3 – Review Aggregator
  4 – Scoring Engine
  5 – Summarizer
  6 – Response Formatter / Done

The generator can be consumed by the SSE endpoint for real-time streaming,
or drained fully by the standard POST endpoint to collect the final result.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.models.business import BusinessListing
from app.models.response import SearchResponse, StreamEvent
from app.modules import (
    IntentParser,
    LocationResolver,
    ResponseFormatter,
    ReviewAggregator,
    ScoringEngine,
    SearchAgent,
    Summarizer,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TOTAL_STEPS = 7


def _make_event(event: str, step: int, data: Dict[str, Any]) -> StreamEvent:
    """Convenience factory for StreamEvent objects."""
    return StreamEvent(event=event, data=data, step=step, total_steps=_TOTAL_STEPS)


async def run_pipeline(
    query: str,
    user_ip: Optional[str] = None,
) -> AsyncGenerator[StreamEvent, None]:
    """
    Execute the full LocalLens pipeline as an async generator.

    Yields one StreamEvent per completed stage.  The final event has
    ``event="done"`` and carries the complete SearchResponse as
    ``data["response"]``.  On unrecoverable errors an ``event="error"``
    event is yielded.

    Parameters
    ----------
    query:
        Raw user query string.
    user_ip:
        Caller's IP address – used for "near_me" geolocation.

    Yields
    ------
    StreamEvent
        One event per pipeline stage, plus a final "done" event.
    """
    start_time = time.monotonic()
    pipeline_steps: List[Dict[str, Any]] = []
    intent_parser = IntentParser()
    location_resolver = LocationResolver()
    search_agent = SearchAgent()
    review_aggregator = ReviewAggregator()
    scoring_engine = ScoringEngine()
    summarizer = Summarizer()
    formatter = ResponseFormatter()

    # ------------------------------------------------------------------ #
    # Step 0 – Intent Parsing
    # ------------------------------------------------------------------ #
    try:
        step_start = time.monotonic()
        intent = await intent_parser.parse(query)
        step_ms = int((time.monotonic() - step_start) * 1000)
        step_meta = {
            "stage": "intent_parser",
            "status": "ok",
            "elapsed_ms": step_ms,
            "category": intent.category,
            "location": intent.location,
            "confidence": intent.confidence,
        }
        pipeline_steps.append(step_meta)
        event = _make_event(
            "intent_parsed",
            step=0,
            data={
                "category": intent.category,
                "location": intent.location,
                "count": intent.count,
                "confidence": intent.confidence,
                "elapsed_ms": step_ms,
            },
        )
        logger.info("pipeline_step", stage="intent_parsed", ms=step_ms)
        yield event
    except Exception as exc:
        logger.error("pipeline_error", stage="intent_parser", error=str(exc))
        yield _make_event("error", step=0, data={"stage": "intent_parser", "error": str(exc)})
        return

    # ------------------------------------------------------------------ #
    # Step 1 – Location Resolution
    # ------------------------------------------------------------------ #
    try:
        step_start = time.monotonic()
        location = await location_resolver.resolve(
            intent.location, radius_km=intent.radius_km, user_ip=user_ip
        )
        step_ms = int((time.monotonic() - step_start) * 1000)
        step_meta = {
            "stage": "location_resolver",
            "status": "ok",
            "elapsed_ms": step_ms,
            "display_name": location.display_name,
            "location_type": location.location_type,
        }
        pipeline_steps.append(step_meta)
        yield _make_event(
            "location_resolved",
            step=1,
            data={
                "display_name": location.display_name,
                "lat": location.coordinates.lat,
                "lng": location.coordinates.lng,
                "location_type": location.location_type,
                "elapsed_ms": step_ms,
            },
        )
        logger.info("pipeline_step", stage="location_resolved", ms=step_ms)
    except Exception as exc:
        logger.error("pipeline_error", stage="location_resolver", error=str(exc))
        yield _make_event("error", step=1, data={"stage": "location_resolver", "error": str(exc)})
        return

    # ------------------------------------------------------------------ #
    # Step 2 – Search
    # ------------------------------------------------------------------ #
    try:
        step_start = time.monotonic()
        raw_listings: List[BusinessListing] = await search_agent.search(intent, location)
        step_ms = int((time.monotonic() - step_start) * 1000)
        step_meta = {
            "stage": "search_agent",
            "status": "ok",
            "elapsed_ms": step_ms,
            "raw_count": len(raw_listings),
        }
        pipeline_steps.append(step_meta)
        yield _make_event(
            "search_complete",
            step=2,
            data={
                "raw_count": len(raw_listings),
                "elapsed_ms": step_ms,
                "sources": list({b.source for b in raw_listings}),
            },
        )
        logger.info("pipeline_step", stage="search_complete", count=len(raw_listings), ms=step_ms)
    except Exception as exc:
        logger.error("pipeline_error", stage="search_agent", error=str(exc))
        yield _make_event("error", step=2, data={"stage": "search_agent", "error": str(exc)})
        return

    # ------------------------------------------------------------------ #
    # Step 3 – Review Aggregation
    # ------------------------------------------------------------------ #
    try:
        step_start = time.monotonic()
        enriched_listings = await review_aggregator.aggregate(raw_listings)
        step_ms = int((time.monotonic() - step_start) * 1000)
        rated_count = sum(
            1 for b in enriched_listings if b.review_data.average_rating is not None
        )
        step_meta = {
            "stage": "review_aggregator",
            "status": "ok",
            "elapsed_ms": step_ms,
            "enriched_count": len(enriched_listings),
            "rated_count": rated_count,
        }
        pipeline_steps.append(step_meta)
        yield _make_event(
            "reviews_aggregated",
            step=3,
            data={
                "enriched_count": len(enriched_listings),
                "rated_count": rated_count,
                "elapsed_ms": step_ms,
            },
        )
        logger.info("pipeline_step", stage="reviews_aggregated", ms=step_ms)
    except Exception as exc:
        logger.error("pipeline_error", stage="review_aggregator", error=str(exc))
        # Non-fatal: continue with unenriched listings
        enriched_listings = raw_listings
        pipeline_steps.append({"stage": "review_aggregator", "status": "error", "error": str(exc)})

    # ------------------------------------------------------------------ #
    # Step 4 – Scoring
    # ------------------------------------------------------------------ #
    try:
        step_start = time.monotonic()
        ranked_listings = scoring_engine.score_and_rank(enriched_listings, intent)
        step_ms = int((time.monotonic() - step_start) * 1000)
        step_meta = {
            "stage": "scoring_engine",
            "status": "ok",
            "elapsed_ms": step_ms,
            "ranked_count": len(ranked_listings),
            "top_score": ranked_listings[0].composite_score if ranked_listings else 0,
        }
        pipeline_steps.append(step_meta)
        yield _make_event(
            "scoring_complete",
            step=4,
            data={
                "ranked_count": len(ranked_listings),
                "top_score": step_meta["top_score"],
                "elapsed_ms": step_ms,
            },
        )
        logger.info("pipeline_step", stage="scoring_complete", ms=step_ms)
    except Exception as exc:
        logger.error("pipeline_error", stage="scoring_engine", error=str(exc))
        ranked_listings = enriched_listings[: intent.count]
        pipeline_steps.append({"stage": "scoring_engine", "status": "error", "error": str(exc)})

    # ------------------------------------------------------------------ #
    # Step 5 – Summarisation
    # ------------------------------------------------------------------ #
    try:
        step_start = time.monotonic()
        summarised_listings = await summarizer.summarise(ranked_listings, intent)
        step_ms = int((time.monotonic() - step_start) * 1000)
        step_meta = {
            "stage": "summarizer",
            "status": "ok",
            "elapsed_ms": step_ms,
            "summarised_count": len(summarised_listings),
        }
        pipeline_steps.append(step_meta)
        yield _make_event(
            "summary_ready",
            step=5,
            data={
                "summarised_count": len(summarised_listings),
                "elapsed_ms": step_ms,
            },
        )
        logger.info("pipeline_step", stage="summary_ready", ms=step_ms)
    except Exception as exc:
        logger.error("pipeline_error", stage="summarizer", error=str(exc))
        summarised_listings = ranked_listings
        pipeline_steps.append({"stage": "summarizer", "status": "error", "error": str(exc)})

    # ------------------------------------------------------------------ #
    # Step 6 – Format & Done
    # ------------------------------------------------------------------ #
    try:
        response: SearchResponse = formatter.format(
            query=query,
            intent=intent,
            location=location,
            listings=summarised_listings,
            pipeline_steps=pipeline_steps,
            start_time=start_time,
        )
        pipeline_steps.append(
            {
                "stage": "response_formatter",
                "status": "ok",
                "elapsed_ms": response.elapsed_ms,
            }
        )
        yield _make_event(
            "done",
            step=6,
            data={"response": response.model_dump(), "elapsed_ms": response.elapsed_ms},
        )
        logger.info("pipeline_done", total_ms=response.elapsed_ms, results=response.total_results)
    except Exception as exc:
        logger.error("pipeline_error", stage="response_formatter", error=str(exc))
        yield _make_event(
            "error",
            step=6,
            data={"stage": "response_formatter", "error": str(exc), "traceback": traceback.format_exc()},
        )
