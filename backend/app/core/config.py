from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    ENVIRONMENT: str = "development"
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    OPENAI_API_KEY: str
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    OPENAI_EMBEDDING_DIMENSIONS: int = 3072
    OPENAI_CHAT_MODEL: str = "gpt-4o"

    DATABASE_URL: str = "sqlite+aiosqlite:///./ragdb.sqlite"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "rag_chunks"
    QDRANT_API_KEY: str | None = None

    # No production default: a missing secret in production fails startup.
    # For local development only, an unset/empty secret falls back to a
    # well-known dev-only value (see the validator below) so that
    # `docker compose up` works with only OPENAI_API_KEY set. Never deploy
    # with ENVIRONMENT=development and the dev secret.
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    CHUNK_SIZE_TOKENS: int = 512
    CHUNK_OVERLAP_TOKENS: int = 64
    RETRIEVAL_TOP_K: int = 5
    # Phase B retrieval: fetch a wider candidate pool, filter by cosine
    # similarity, then select a diverse final set with MMR.
    # Threshold default 0.30: for text-embedding-3-large, cosine scores
    # below ~0.3 are typically off-topic in practice. This is a sensible
    # starting default, NOT a measured optimum -- Phase D must measure
    # hit-rate/recall at several thresholds before claiming it is tuned.
    RETRIEVAL_SIMILARITY_THRESHOLD: float = 0.30
    RETRIEVAL_FETCH_K: int = 20
    MMR_LAMBDA: float = 0.7
    # Generation budgets (Phase B): context is truncated lowest-score
    # first when it would exceed this; history is truncated most-recent
    # first; chat completions are capped at CHAT_MAX_TOKENS.
    MAX_CONTEXT_TOKENS: int = 6000
    HISTORY_MAX_TOKENS: int = 2000
    CHAT_MAX_TOKENS: int = 1000

    @field_validator("OPENAI_EMBEDDING_DIMENSIONS")
    @classmethod
    def _validate_dims(cls, v: int) -> int:
        # text-embedding-3-large supports 1..3072 via `dimensions`.
        if not 1 <= v <= 3072:
            raise ValueError("OPENAI_EMBEDDING_DIMENSIONS must be in 1..3072")
        return v

    @field_validator("RETRIEVAL_SIMILARITY_THRESHOLD", "MMR_LAMBDA")
    @classmethod
    def _validate_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("value must be in 0..1")
        return v

    @model_validator(mode="after")
    def _dev_jwt_secret(self) -> "Settings":
        if self.JWT_SECRET_KEY:
            return self
        if (self.ENVIRONMENT or "development").lower() == "production":
            raise ValueError("JWT_SECRET_KEY must be set in production")
        logger.warning(
            "JWT_SECRET_KEY is not set; using a dev-only insecure secret. "
            "Do not use this configuration outside local development."
        )
        self.JWT_SECRET_KEY = "dev-only-insecure-secret-change-me-in-production"
        return self

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: str | List[str]) -> List[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                import json

                try:
                    return json.loads(v_stripped)
                except Exception:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


@lru_cache
def get_settings() -> Settings:
    return Settings()
