"""
Metrics endpoint.

GET /metrics returns aggregate runtime statistics.

Counters are stored in a simple module-level dict and reset on process restart.
For production use, consider replacing with a Prometheus exporter.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.utils.logger import get_logger

router = APIRouter(tags=["Metrics"])
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# In-process metrics store (thread-safe reads, not write-concurrent)
# ---------------------------------------------------------------------------

_metrics: dict = {
    "total_queries": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "total_errors": 0,
    "total_latency_ms": 0,
}


def record_query(elapsed_ms: int, cache_hit: bool = False) -> None:
    """
    Increment query counters.  Call this from the search route handler.

    Parameters
    ----------
    elapsed_ms:
        Pipeline execution time for this query.
    cache_hit:
        True if the result was served from cache.
    """
    _metrics["total_queries"] += 1
    _metrics["total_latency_ms"] += elapsed_ms
    if cache_hit:
        _metrics["cache_hits"] += 1
    else:
        _metrics["cache_misses"] += 1


def record_error() -> None:
    """Increment the error counter."""
    _metrics["total_errors"] += 1


@router.get("/metrics", summary="Runtime performance metrics")
async def get_metrics() -> dict:
    """
    Return aggregate performance metrics for the current process.

    Returns
    -------
    dict
        JSON with ``total_queries``, ``cache_hit_rate``, ``avg_latency_ms``,
        and ``errors`` fields.
    """
    total = _metrics["total_queries"]
    hits = _metrics["cache_hits"]
    misses = _metrics["cache_misses"]
    total_latency = _metrics["total_latency_ms"]

    cache_hit_rate = (hits / (hits + misses)) if (hits + misses) > 0 else 0.0
    avg_latency = (total_latency / total) if total > 0 else 0.0

    return {
        "total_queries": total,
        "cache_hit_rate": round(cache_hit_rate, 4),
        "avg_latency_ms": round(avg_latency, 1),
        "errors": _metrics["total_errors"],
        "cache_hits": hits,
        "cache_misses": misses,
    }
