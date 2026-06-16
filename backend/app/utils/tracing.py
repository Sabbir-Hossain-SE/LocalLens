"""
Langfuse tracing utilities.

Provides a singleton Langfuse client + two decorators:

  - ``@trace_stage(name)``  — for pipeline stage functions
  - ``@trace_llm(name)``    — for LLM call sites, captures prompt + response

Both decorators are NO-OPS when Langfuse credentials are not configured. This
keeps tests + local-dev hassle-free: you only see traces when you set the
environment variables, but the codepaths always work.

PDF §6.2: "All agent steps are traced in Langfuse — no silent or untracked
LLM calls in production flow."
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_langfuse_client: Any = None
_langfuse_checked = False


def _get_client() -> Optional[Any]:
    """Lazily construct the Langfuse client. Returns None if not configured."""
    global _langfuse_client, _langfuse_checked
    if _langfuse_checked:
        return _langfuse_client

    _langfuse_checked = True
    settings = get_settings()
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        logger.info("langfuse_not_configured")
        return None
    try:
        from langfuse import Langfuse  # type: ignore

        _langfuse_client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        logger.info("langfuse_ready", host=settings.LANGFUSE_HOST)
    except Exception as exc:
        logger.warning("langfuse_init_failed", error=str(exc))
        _langfuse_client = None
    return _langfuse_client


def trace_stage(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that wraps a pipeline stage in a Langfuse span.

    Works for both sync and async functions. The first positional argument
    (after ``self`` if it's a method) is serialised as the input; the return
    value is serialised as the output. On exception the span is closed with
    a status_message; the exception still propagates.
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        is_async = inspect.iscoroutinefunction(fn)

        if is_async:
            @functools.wraps(fn)
            async def aw(*args: Any, **kwargs: Any) -> Any:
                client = _get_client()
                if client is None:
                    return await fn(*args, **kwargs)
                span = client.span(name=name, input=_safe_repr(args, kwargs))
                try:
                    result = await fn(*args, **kwargs)
                    span.end(output=_safe_repr(result))
                    return result
                except Exception as exc:
                    span.end(level="ERROR", status_message=str(exc))
                    raise
            return aw

        @functools.wraps(fn)
        def w(*args: Any, **kwargs: Any) -> Any:
            client = _get_client()
            if client is None:
                return fn(*args, **kwargs)
            span = client.span(name=name, input=_safe_repr(args, kwargs))
            try:
                result = fn(*args, **kwargs)
                span.end(output=_safe_repr(result))
                return result
            except Exception as exc:
                span.end(level="ERROR", status_message=str(exc))
                raise
        return w

    return deco


def trace_llm(name: str, model: Optional[str] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that records an LLM call as a Langfuse generation.

    Expects the wrapped function to accept a prompt as its first argument
    (after ``self``) and return a string (or an object whose ``str()``
    representation is the model output).
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        is_async = inspect.iscoroutinefunction(fn)

        if is_async:
            @functools.wraps(fn)
            async def aw(*args: Any, **kwargs: Any) -> Any:
                client = _get_client()
                if client is None:
                    return await fn(*args, **kwargs)
                prompt = _extract_prompt(args, kwargs)
                gen = client.generation(name=name, model=model, input=prompt)
                try:
                    result = await fn(*args, **kwargs)
                    gen.end(output=_safe_repr(result))
                    return result
                except Exception as exc:
                    gen.end(level="ERROR", status_message=str(exc))
                    raise
            return aw

        @functools.wraps(fn)
        def w(*args: Any, **kwargs: Any) -> Any:
            client = _get_client()
            if client is None:
                return fn(*args, **kwargs)
            prompt = _extract_prompt(args, kwargs)
            gen = client.generation(name=name, model=model, input=prompt)
            try:
                result = fn(*args, **kwargs)
                gen.end(output=_safe_repr(result))
                return result
            except Exception as exc:
                gen.end(level="ERROR", status_message=str(exc))
                raise
        return w

    return deco


def _extract_prompt(args: tuple, kwargs: dict) -> str:
    """Pull the prompt string out of (self, prompt) or (prompt,) call shapes."""
    if "prompt" in kwargs:
        return str(kwargs["prompt"])
    # Skip self if it's a bound method call
    candidates = args[1:] if args and hasattr(args[0], "__class__") else args
    return str(candidates[0]) if candidates else ""


def _safe_repr(*objs: Any) -> str:
    """Truncate long values so the Langfuse UI stays readable."""
    s = " | ".join(repr(o) for o in objs)
    return s[:4000] + ("…" if len(s) > 4000 else "")


def flush() -> None:
    """Force any buffered events to send. Call at process shutdown."""
    client = _get_client()
    if client is not None:
        try:
            client.flush()
        except Exception as exc:
            logger.warning("langfuse_flush_failed", error=str(exc))
