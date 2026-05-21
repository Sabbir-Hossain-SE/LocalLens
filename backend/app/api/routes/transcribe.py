"""
POST /transcribe — voice-input transcription endpoint (PDF §7.1).

Accepts a multipart audio upload (any format Whisper supports: WebM, MP4, WAV,
MP3, OGG) and returns ``{"text": "..."}`` for the recognised speech. The text
can then be fed into the normal search flow.

Uses OpenAI Whisper running locally (the ``openai-whisper`` package). The
``base`` model (~139 MB) is the default — it's small enough to be quick on
CPU and accurate enough for short search queries. The model is lazily loaded
on first request and cached in-process.

Graceful degradation: if ``openai-whisper`` is not installed the endpoint
returns 503 with an explanatory message; the rest of the API keeps working.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Voice"])

_whisper_model: Any = None
_whisper_checked = False
_MODEL_NAME = "base"  # tradeoff: ~140 MB, English-strong, ~5x realtime on CPU


def _get_model() -> Optional[Any]:
    """Lazily load the Whisper model. Returns None if the package is missing."""
    global _whisper_model, _whisper_checked
    if _whisper_checked:
        return _whisper_model
    _whisper_checked = True
    try:
        import whisper  # type: ignore

        logger.info("whisper_loading", model=_MODEL_NAME)
        _whisper_model = whisper.load_model(_MODEL_NAME)
        logger.info("whisper_loaded", model=_MODEL_NAME)
    except Exception as exc:
        logger.warning("whisper_unavailable", reason=str(exc))
        _whisper_model = None
    return _whisper_model


class TranscribeResponse(BaseModel):
    """Response payload for /transcribe."""

    text: str
    language: Optional[str] = None
    duration_s: Optional[float] = None


@router.post(
    "/transcribe",
    response_model=TranscribeResponse,
    summary="Transcribe an audio recording into search-ready text",
)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    """
    Transcribe an uploaded audio blob and return the recognised text.

    The audio is written to a temp file (Whisper expects a filesystem path),
    transcribed in a thread pool executor (the model is sync), and the temp
    file is cleaned up before the response is returned.
    """
    model = _get_model()
    if model is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Whisper is not installed on this server. "
                "Install with: pip install openai-whisper"
            ),
        )

    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    try:
        body = await audio.read()
    finally:
        await audio.close()

    if not body:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(body)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: model.transcribe(str(tmp_path), language=None, fp16=False),
        )
        text = (result.get("text") or "").strip()
        language = result.get("language")
        logger.info("transcribe_ok", chars=len(text), language=language)
        return TranscribeResponse(text=text, language=language)
    except Exception as exc:
        logger.warning("transcribe_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
