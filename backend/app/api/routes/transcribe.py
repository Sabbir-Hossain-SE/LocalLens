"""
POST /transcribe - voice-input transcription endpoint.

The LocalLens backend stays lightweight: it forwards browser audio to a
remote Whisper service, usually running on a stronger machine reachable over
Tailscale. The remote service is responsible for OpenAI Whisper, ffmpeg, and
model storage.
"""

from __future__ import annotations

from typing import Optional

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Voice"])


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
    Forward an uploaded audio blob to the configured remote Whisper service.

    Expected remote API shape:
      POST /transcribe multipart form field "audio"
      -> {"text": "...", "language": "..."}
    """
    settings = get_settings()
    if not settings.WHISPER_REMOTE_URL:
        raise HTTPException(
            status_code=503,
            detail=(
                "Remote Whisper is not configured. Set WHISPER_REMOTE_URL "
                "to your Tailscale Whisper server /transcribe endpoint."
            ),
        )

    try:
        body = await audio.read()
    finally:
        await audio.close()

    if not body:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    filename = audio.filename or "audio.webm"
    content_type = audio.content_type or "application/octet-stream"
    files = {"audio": (filename, body, content_type)}

    try:
        async with httpx.AsyncClient(timeout=settings.WHISPER_REMOTE_TIMEOUT_SECONDS) as client:
            resp = await client.post(settings.WHISPER_REMOTE_URL, files=files)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        logger.warning(
            "remote_whisper_http_error",
            status=exc.response.status_code,
            detail=detail,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Remote Whisper failed ({exc.response.status_code}): {detail}",
        )
    except Exception as exc:
        logger.warning("remote_whisper_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Remote Whisper unavailable: {exc}")

    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="Remote Whisper returned empty text")

    language = payload.get("language")
    duration_s = payload.get("duration_s")
    logger.info("transcribe_ok", chars=len(text), language=language, provider="remote")
    return TranscribeResponse(text=text, language=language, duration_s=duration_s)
