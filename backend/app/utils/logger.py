"""
Structured logging setup using structlog.

Call `get_logger(__name__)` in any module to get a bound logger with
the module name pre-attached. All logs are emitted as JSON in production
and as colourised key-value pairs in development.
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from typing import Any

import structlog

from app.config import get_settings


def _configure_structlog() -> None:
    """Set up structlog with console-friendly rendering."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer() if sys.stdout.isatty() else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configured = False


def get_logger(name: str = "locallens", **initial_values: Any) -> Any:
    """
    Return a structlog BoundLogger bound to the given module name.

    Parameters
    ----------
    name:
        Usually ``__name__`` of the calling module.
    **initial_values:
        Extra key-value pairs permanently bound to this logger instance.
    """
    global _configured
    if not _configured:
        _configure_structlog()
        _configured = True

    return structlog.get_logger(name).bind(**initial_values)
