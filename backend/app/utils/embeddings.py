"""
Embedding utilities for semantic business search (PDF §7.2).

Singleton wrapper around ``sentence-transformers/all-MiniLM-L6-v2`` (384-dim).
Embeddings are computed lazily on first use; the model itself is cached as a
process-global to avoid re-loading on every request.

All functions degrade gracefully when ``sentence-transformers`` is not
installed: ``embed_text`` returns ``None`` and ``cosine_similarity`` falls
back to 0.0. Callers should treat the absence of semantic data as "skip
semantic ranking" rather than fail.
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_model: Any = None
_model_checked = False
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _get_model() -> Optional[Any]:
    """Lazily load the sentence-transformer. Returns None if unavailable."""
    global _model, _model_checked
    if _model_checked:
        return _model
    _model_checked = True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("embedding_model_loaded", model=_MODEL_NAME)
    except Exception as exc:
        logger.info("embedding_model_unavailable", reason=str(exc))
        _model = None
    return _model


def embed_text(text: str) -> Optional[List[float]]:
    """Encode a single string into a 384-dim vector; None if disabled."""
    if not text:
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vec.tolist()
    except Exception as exc:
        logger.warning("embedding_encode_error", error=str(exc))
        return None


def embed_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """Encode a batch of strings. None entries for empty inputs / failures."""
    model = _get_model()
    if model is None:
        return [None] * len(texts)
    try:
        non_empty_idx = [i for i, t in enumerate(texts) if t]
        if not non_empty_idx:
            return [None] * len(texts)
        non_empty_texts = [texts[i] for i in non_empty_idx]
        vecs = model.encode(
            non_empty_texts, convert_to_numpy=True, normalize_embeddings=True
        )
        out: List[Optional[List[float]]] = [None] * len(texts)
        for j, i in enumerate(non_empty_idx):
            out[i] = vecs[j].tolist()
        return out
    except Exception as exc:
        logger.warning("embedding_batch_error", error=str(exc))
        return [None] * len(texts)


def cosine_similarity(a: Optional[List[float]], b: Optional[List[float]]) -> float:
    """
    Cosine similarity between two unit-normalised vectors, in [0, 1] after
    clipping. Returns 0.0 if either vector is missing.

    Both vectors are expected to already be L2-normalised (which is what
    ``normalize_embeddings=True`` does at encode time), so this reduces to
    a simple dot product.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # Map [-1, 1] → [0, 1] so it composes with the other 0-1 score signals.
    return max(0.0, min(1.0, (dot + 1.0) / 2.0))
