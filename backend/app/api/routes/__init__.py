"""Route modules for the LocalLens API."""

from .health import router as health_router
from .metrics import router as metrics_router
from .search import router as search_router

__all__ = ["health_router", "metrics_router", "search_router"]
