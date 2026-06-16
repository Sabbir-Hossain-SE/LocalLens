"""
LocalLens Backend – FastAPI application entry point.

Startup sequence:
  1. Validate settings
  2. Initialise the disk cache
  3. Load scoring weights
  4. Probe LLM connectivity (warning only – not fatal)
  5. Mount all routers

Run with:
    uvicorn app.main:app --reload --port 8000
or:
    python -m app.main
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    health_router,
    metrics_router,
    search_router,
    transcribe_router,
)
from app.config import get_settings
from app.modules.scoring_engine import _load_weights
from app.utils.cache import CacheManager
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Application lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Async context manager that runs startup and shutdown logic."""
    # ---- Startup ----
    logger.info("locallens_starting", version="1.0.0")

    # 1. Initialise cache
    cache = CacheManager()
    stats = cache.stats()
    logger.info("cache_ready", entries=stats.get("size"), dir=stats.get("directory"))

    # 2. Load scoring weights
    try:
        weights = _load_weights()
        logger.info("scoring_weights_loaded", categories=list(weights.get("category_overrides", {}).keys()))
    except Exception as exc:
        logger.warning("scoring_weights_load_failed", error=str(exc))

    # 3. Probe LLM (non-fatal)
    await _probe_llm()

    logger.info("locallens_ready", port=settings.API_PORT)
    yield
    # ---- Shutdown ----
    logger.info("locallens_shutdown")


async def _probe_llm() -> None:
    """Non-blocking LLM connectivity probe – logs a warning if unreachable."""
    try:
        if settings.LLM_PROVIDER == "ollama":
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                if resp.status_code == 200:
                    models = [m.get("name") for m in resp.json().get("models", [])]
                    logger.info("ollama_reachable", models=models)
                else:
                    logger.warning("ollama_unhealthy", status=resp.status_code)
        elif settings.LLM_PROVIDER == "groq":
            if settings.GROQ_API_KEY:
                logger.info("groq_api_key_present")
            else:
                logger.warning("groq_api_key_missing")
    except Exception as exc:
        logger.warning(
            "llm_probe_failed",
            provider=settings.LLM_PROVIDER,
            error=str(exc),
            hint="Pipeline will use template-based fallbacks",
        )


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LocalLens API",
    description=(
        "Conversational AI agent that translates plain-English questions into "
        "ranked, summarised lists of local businesses."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers ----
app.include_router(search_router)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(transcribe_router)


# ---- Root ----
@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    """Redirect hint for the API root."""
    return JSONResponse(
        {
            "name": "LocalLens API",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/api/v1/health",
        }
    )


# ---------------------------------------------------------------------------
# Direct execution entry point
# ---------------------------------------------------------------------------

def run() -> None:
    """Start the Uvicorn server (used by the ``locallens`` CLI entry point)."""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.API_PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    run()
