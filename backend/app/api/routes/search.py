"""
Search endpoints.

POST /search           – synchronous full-pipeline run, returns SearchResponse JSON.
GET  /search/stream    – SSE streaming, yields StreamEvents as JSON while pipeline runs.

Both endpoints cache results keyed on (query, approximate_location) with
the configured CACHE_TTL_SECONDS.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.models.intent import HistoryTurn
from app.models.response import SearchResponse, StreamEvent
from app.pipeline.orchestrator import run_pipeline
from app.utils.cache import CacheManager
from app.utils.logger import get_logger

from .metrics import record_error, record_query

router = APIRouter(tags=["Search"])
logger = get_logger(__name__)
_cache = CacheManager()


# ---------------------------------------------------------------------------
# Request / helper models
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    """Request body for POST /search."""

    query: str
    user_ip: Optional[str] = None
    # PDF §7.1 conversational memory: last few turns so the intent parser can
    # detect follow-ups like "show me cheaper options" or "open now".
    history: Optional[list[HistoryTurn]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_client_ip(request: Request) -> Optional[str]:
    """
    Extract the real client IP address from the request.

    Checks X-Forwarded-For first (when behind a proxy), then falls back
    to the direct connection address.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


async def _drain_pipeline(
    query: str, user_ip: Optional[str], history: Optional[list[HistoryTurn]] = None
) -> SearchResponse:
    """
    Run the pipeline to completion and return the final SearchResponse.

    Collects all stream events and returns only the last ``done`` event's
    response payload.  Raises HTTPException on pipeline failure.
    """
    async for event in run_pipeline(query, user_ip, history=history):
        if event.event == "done":
            response_data = event.data.get("response")
            if response_data:
                return SearchResponse(**response_data)
        elif event.event == "error":
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline error at step {event.step}: {event.data.get('error')}",
            )
    raise HTTPException(status_code=500, detail="Pipeline completed without a done event")


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------

@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search for local businesses (synchronous)",
    response_description="Ranked list of businesses matching the query",
)
async def search(body: SearchRequest, request: Request) -> SearchResponse:
    """
    Run the full LocalLens pipeline and return a ranked list of businesses.

    Results are cached using ``(query, location)`` as the cache key.
    Subsequent identical queries are served from cache.

    Parameters
    ----------
    body:
        JSON body with ``query`` (required) and optional ``user_ip``.
    request:
        FastAPI Request object – used to extract the real client IP if
        ``user_ip`` is not provided explicitly.

    Returns
    -------
    SearchResponse
        Ranked, summarised business listings.
    """
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    user_ip = body.user_ip or _extract_client_ip(request)

    # Try cache (approximate key – location part resolved after intent parse)
    cache_key = _cache.make_search_key(query, user_ip or "default")
    cached = _cache.get(cache_key)
    if cached:
        logger.info("search_cache_hit", query=query[:60])
        record_query(elapsed_ms=0, cache_hit=True)
        return SearchResponse(**cached) if isinstance(cached, dict) else cached

    start = time.monotonic()
    try:
        response = await _drain_pipeline(query, user_ip, history=body.history)
        _cache.set(cache_key, response.model_dump())
        record_query(elapsed_ms=response.elapsed_ms, cache_hit=False)
        return response
    except HTTPException:
        record_error()
        raise
    except Exception as exc:
        record_error()
        logger.error("search_unhandled_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /search/stream
# ---------------------------------------------------------------------------

@router.get(
    "/search/stream",
    summary="Search for local businesses (SSE streaming)",
    response_description="Server-Sent Events stream of pipeline progress and results",
)
async def search_stream(
    request: Request,
    query: str = Query(..., description="Natural language search query"),
    user_ip: Optional[str] = Query(default=None, description="Override caller IP for geolocation"),
    prev_query: Optional[str] = Query(default=None, description="Previous user query (follow-up context)"),
    prev_category: Optional[str] = Query(default=None, description="Previous resolved category"),
    prev_location: Optional[str] = Query(default=None, description="Previous resolved location"),
) -> EventSourceResponse:
    """
    Stream pipeline progress as Server-Sent Events.

    Each event carries a ``StreamEvent`` JSON payload.  The final event has
    ``event="done"`` and includes the complete SearchResponse.

    Clients should listen with the browser's ``EventSource`` API or any
    SSE-capable HTTP client.

    Parameters
    ----------
    query:
        Natural language search query.
    user_ip:
        Optional IP override – defaults to the request's remote address.
    """
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    effective_ip = user_ip or _extract_client_ip(request)
    history: Optional[list[HistoryTurn]] = None
    if prev_query:
        history = [
            HistoryTurn(
                query=prev_query,
                category=prev_category,
                location=prev_location,
            )
        ]

    async def event_generator() -> AsyncGenerator[dict, None]:
        async def wait_for_disconnect() -> bool:
            while True:
                if await request.is_disconnected():
                    return True
                await asyncio.sleep(0.25)

        pipeline = run_pipeline(query.strip(), effective_ip, history=history)
        try:
            while True:
                next_event = asyncio.create_task(pipeline.__anext__())
                disconnected = asyncio.create_task(wait_for_disconnect())
                done, pending = await asyncio.wait(
                    {next_event, disconnected},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if disconnected in done and disconnected.result():
                    logger.info("sse_client_disconnected", query=query[:60])
                    next_event.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_event
                    await pipeline.aclose()
                    break

                disconnected.cancel()
                with suppress(asyncio.CancelledError):
                    await disconnected

                try:
                    stream_event = next_event.result()
                except StopAsyncIteration:
                    break

                payload = stream_event.model_dump_json()
                yield {"event": stream_event.event, "data": payload}

                if await request.is_disconnected():
                    logger.info("sse_client_disconnected", query=query[:60])
                    await pipeline.aclose()
                    break

                if stream_event.event in ("done", "error"):
                    # Record metrics on stream completion
                    if stream_event.event == "done":
                        elapsed = stream_event.data.get("elapsed_ms", 0)
                        record_query(elapsed_ms=elapsed, cache_hit=False)
                    else:
                        record_error()
                    break
        except asyncio.CancelledError:
            logger.info("sse_generator_cancelled", query=query[:60])
            await pipeline.aclose()
            raise
        except Exception as exc:
            logger.error("sse_generator_error", error=str(exc))
            record_error()
            error_event = StreamEvent(
                event="error",
                data={"error": str(exc)},
                step=0,
                total_steps=7,
            )
            yield {"event": "error", "data": error_event.model_dump_json()}

    return EventSourceResponse(event_generator())
