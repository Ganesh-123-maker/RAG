from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    ENVIRONMENT: str = "development"
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

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
    # Phase C: retrieval is graded "good" only if its top score meets
    # this stricter bar. 0.50 is an unmeasured starting point, NOT a
    # tuned optimum -- Phase D must measure grade thresholds before
    # claiming any of them is tuned.
    RETRIEVAL_GRADE_THRESHOLD: float = 0.50
    RETRIEVAL_FETCH_K: int = 20
    MMR_LAMBDA: float = 0.7
    # Generation budgets (Phase B): context is truncated lowest-score
    # first when it would exceed this; history is truncated most-recent
    # first; chat completions are capped at CHAT_MAX_TOKENS.
    MAX_CONTEXT_TOKENS: int = 6000
    HISTORY_MAX_TOKENS: int = 2000
    CHAT_MAX_TOKENS: int = 1000

    # Phase E hardening (all single-instance / in-memory unless noted).
    # RATE_LIMIT_ENABLED=None means: on everywhere except ENVIRONMENT=test
    # (the test suite makes many calls as one user in one process).
    RATE_LIMIT_ENABLED: bool | None = None
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10
    UPLOAD_RATE_LIMIT_PER_MINUTE: int = 10
    CHAT_RATE_LIMIT_PER_MINUTE: int = 30
    # Per-user daily quotas. The token budget is an ESTIMATE (the agent
    # service does not return metered usage): question+answer chars / 4.
    # It is a cost guard, not a billing measurement — never present it
    # as metered OpenAI usage.
    DAILY_CHAT_REQUESTS: int = 200
    DAILY_TOKEN_BUDGET_EST: int = 200000
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 3
    CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 60.0
    INGESTION_MAX_ATTEMPTS: int = 2
    # Optional Sentry DSN. Absent (the default) means no-op: Sentry is
    # never required to boot and no spans/errors leave the process.
    SENTRY_DSN: str | None = None

    @field_validator("OPENAI_EMBEDDING_DIMENSIONS")
    @classmethod
    def _validate_dims(cls, v: int) -> int:
        # text-embedding-3-large supports 1..3072 via `dimensions`.
        if not 1 <= v <= 3072:
            raise ValueError("OPENAI_EMBEDDING_DIMENSIONS must be in 1..3072")
        return v

    @field_validator(
        "RETRIEVAL_SIMILARITY_THRESHOLD", "RETRIEVAL_GRADE_THRESHOLD", "MMR_LAMBDA"
    )
    @classmethod
    def _validate_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("value must be in 0..1")
        return v

    @field_validator(
        "MAX_UPLOAD_SIZE_MB",
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "RETRIEVAL_TOP_K",
        "RETRIEVAL_FETCH_K",
        "AUTH_RATE_LIMIT_PER_MINUTE",
        "UPLOAD_RATE_LIMIT_PER_MINUTE",
        "CHAT_RATE_LIMIT_PER_MINUTE",
        "DAILY_CHAT_REQUESTS",
        "DAILY_TOKEN_BUDGET_EST",
        "LOGIN_MAX_FAILED_ATTEMPTS",
        "LOCKOUT_MINUTES",
        "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        "INGESTION_MAX_ATTEMPTS",
    )
    @classmethod
    def _validate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("value must be positive")
        return v

    @model_validator(mode="after")
    def _cross_field_checks(self) -> Settings:
        if self.RETRIEVAL_TOP_K > self.RETRIEVAL_FETCH_K:
            raise ValueError("RETRIEVAL_TOP_K must be <= RETRIEVAL_FETCH_K")
        if self.CHUNK_OVERLAP_TOKENS >= self.CHUNK_SIZE_TOKENS:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be < CHUNK_SIZE_TOKENS")
        # CORS with credentials: a wildcard origin is a misconfiguration.
        # Fail loudly in production; warn loudly elsewhere (the app
        # still boots locally, but the warning is in the startup log).
        origins = self.BACKEND_CORS_ORIGINS or []
        if "*" in origins:
            if (self.ENVIRONMENT or "development").lower() == "production":
                raise ValueError(
                    "BACKEND_CORS_ORIGINS must not contain '*' in production "
                    "when credentials are allowed"
                )
            logger.warning(
                "BACKEND_CORS_ORIGINS contains '*'; with allow_credentials "
                "this is unsafe outside local development."
            )
        return self

    @model_validator(mode="after")
    def _dev_jwt_secret(self) -> Settings:
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
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                import json

                try:
                    return json.loads(v_stripped)
                except Exception:  # noqa: BLE001, S110 -- non-JSON string is not an error here
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
