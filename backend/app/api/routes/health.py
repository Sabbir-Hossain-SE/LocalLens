"""
Health check endpoint.

GET /health returns the service status, version, and a quick connectivity
check for the configured LLM backend.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter

from app.config import get_settings
from app.utils.cache import CacheManager
from app.utils.logger import get_logger

router = APIRouter(tags=["Health"])
logger = get_logger(__name__)


@router.get("/health", summary="Service health check")
async def health_check() -> dict:
    """
    Return a simple health status for the API.

    Checks:
    - Basic service is running (always OK if this handler executes)
    - LLM backend reachability (non-blocking)
    - Cache status

    Returns
    -------
    dict
        JSON with ``status``, ``version``, ``llm_provider``, ``llm_reachable``,
        and ``cache_status`` fields.
    """
    settings = get_settings()
    cache = CacheManager()

    # Check LLM reachability
    llm_reachable = False
    try:
        if settings.LLM_PROVIDER == "ollama":
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                llm_reachable = resp.status_code == 200
        elif settings.LLM_PROVIDER == "groq":
            llm_reachable = bool(settings.GROQ_API_KEY)
    except Exception:
        llm_reachable = False

    cache_stats = cache.stats()

    return {
        "status": "healthy",
        "version": "1.0.0",
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "llm_reachable": llm_reachable,
        "voice_transcription": {
            "provider": "remote_whisper",
            "configured": bool(settings.WHISPER_REMOTE_URL),
        },
        "cache_status": {
            "entries": cache_stats.get("size", 0),
            "volume_bytes": cache_stats.get("volume_bytes", 0),
        },
    }
