"""
Application configuration loaded from environment variables via pydantic-settings.

All settings can be overridden by creating a .env file in the backend root or
by setting environment variables directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration object for the LocalLens backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM configuration
    LLM_PROVIDER: str = Field(default="ollama", description="LLM provider: 'ollama' or 'groq'")
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434", description="Base URL for local Ollama server"
    )
    GROQ_API_KEY: str = Field(default="", description="Groq API key (optional, fallback LLM)")
    LLM_MODEL: str = Field(default="llama3", description="Model name to use for LLM calls")

    # Cache configuration
    CACHE_TTL_SECONDS: int = Field(default=3600, description="How long to keep cache entries (s)")
    CACHE_DIR: str = Field(default=".cache", description="Filesystem path for diskcache storage")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Python logging level")

    # API
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins (JSON array or comma-separated)",
    )
    API_PORT: int = Field(default=8000, description="Port the Uvicorn server listens on")

    # Default location fallback when IP geolocation is unavailable
    DEFAULT_LOCATION_LAT: float = Field(default=40.7128, description="Default latitude (NYC)")
    DEFAULT_LOCATION_LNG: float = Field(default=-74.0060, description="Default longitude (NYC)")
    DEFAULT_LOCATION_NAME: str = Field(
        default="New York, NY", description="Human-readable default location name"
    )

    # Voice transcription
    WHISPER_REMOTE_URL: str = Field(
        default="",
        description="Remote Whisper /transcribe URL, e.g. http://100.x.y.z:9001/transcribe",
    )
    WHISPER_REMOTE_TIMEOUT_SECONDS: float = Field(
        default=120.0,
        description="Timeout for forwarding uploaded audio to remote Whisper",
    )

    # Langfuse observability (PDF §6.2: "all agent steps traced in Langfuse")
    LANGFUSE_PUBLIC_KEY: str = Field(default="", description="Langfuse public key (pk-lf-...)")
    LANGFUSE_SECRET_KEY: str = Field(default="", description="Langfuse secret key (sk-lf-...)")
    LANGFUSE_HOST: str = Field(
        default="http://localhost:3001",
        description="Langfuse server URL (self-hosted or https://cloud.langfuse.com)",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> List[str]:
        """Allow CORS_ORIGINS to be supplied as a comma-separated string."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v  # type: ignore[return-value]

    @field_validator("LLM_PROVIDER", mode="before")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Ensure the LLM provider is one of the supported options."""
        allowed = {"ollama", "groq"}
        v = v.lower().strip()
        if v not in allowed:
            raise ValueError(f"LLM_PROVIDER must be one of {allowed}, got '{v}'")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return Settings()
