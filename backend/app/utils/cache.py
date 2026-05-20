"""
Disk-backed cache wrapper built on top of diskcache.

Provides a simple async-compatible interface for storing and retrieving
pipeline results. Cache keys are derived by hashing the query + location
string so identical searches return instantly without hitting external APIs.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

import diskcache

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Module-level singleton – initialised lazily on first use
_cache_instance: Optional[diskcache.Cache] = None


def _get_cache() -> diskcache.Cache:
    """Return (and lazily create) the global diskcache.Cache instance."""
    global _cache_instance
    if _cache_instance is None:
        settings = get_settings()
        cache_dir = os.path.abspath(settings.CACHE_DIR)
        os.makedirs(cache_dir, exist_ok=True)
        _cache_instance = diskcache.Cache(cache_dir)
        logger.info("cache_initialised", path=cache_dir)
    return _cache_instance


class CacheManager:
    """
    High-level cache manager with TTL support.

    All public methods are synchronous but safe to call from async contexts
    (diskcache operations are fast file I/O wrapped in a thread lock).
    """

    def __init__(self) -> None:
        self._cache = _get_cache()
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a value by key.

        Returns ``None`` if the key does not exist or has expired.
        """
        try:
            value = self._cache.get(key)
            if value is not None:
                logger.debug("cache_hit", key=key[:40])
            return value
        except Exception as exc:
            logger.warning("cache_get_error", key=key[:40], error=str(exc))
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Store *value* under *key* with an optional TTL in seconds.

        Falls back to the global CACHE_TTL_SECONDS when *ttl* is not provided.
        Returns ``True`` on success.
        """
        effective_ttl = ttl if ttl is not None else self._settings.CACHE_TTL_SECONDS
        try:
            self._cache.set(key, value, expire=effective_ttl)
            logger.debug("cache_set", key=key[:40], ttl=effective_ttl)
            return True
        except Exception as exc:
            logger.warning("cache_set_error", key=key[:40], error=str(exc))
            return False

    def delete(self, key: str) -> bool:
        """Remove a single entry from the cache. Returns ``True`` if found."""
        try:
            return bool(self._cache.delete(key))
        except Exception as exc:
            logger.warning("cache_delete_error", key=key[:40], error=str(exc))
            return False

    def clear(self) -> int:
        """Evict all entries. Returns the number of entries removed."""
        try:
            count = len(self._cache)
            self._cache.clear()
            logger.info("cache_cleared", evicted=count)
            return count
        except Exception as exc:
            logger.warning("cache_clear_error", error=str(exc))
            return 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def make_search_key(self, query: str, location: str) -> str:
        """
        Generate a stable cache key for a (query, location) pair.

        The key is a SHA-256 hex digest so it is filesystem-safe and
        bounded in length regardless of query complexity.
        """
        raw = json.dumps({"q": query.lower().strip(), "loc": location.lower().strip()})
        return "search:" + hashlib.sha256(raw.encode()).hexdigest()

    def stats(self) -> dict:
        """Return basic statistics about the cache."""
        try:
            return {
                "size": len(self._cache),
                "volume_bytes": self._cache.volume(),
                "directory": str(self._cache.directory),
            }
        except Exception:
            return {"size": 0, "volume_bytes": 0, "directory": "unknown"}
