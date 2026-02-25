from __future__ import annotations
from functools import lru_cache
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "Real-Time Aggregator"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # ── Authentication ───────────────────────────────────────────────────────
    API_KEY: str  # required — no default, forces explicit configuration

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # ── Database ─────────────────────────────────────────────────────────────
    DB_USER: str  # required — no default
    DB_PASSWORD: str  # required — no default
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "aggregator"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_PASSWORD: str = ""
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_POOL_SIZE: int = 20
    REDIS_SOCKET_TIMEOUT: float = 2.0
    REDIS_CONNECT_TIMEOUT: float = 2.0

    @property
    def REDIS_URL(self) -> str:
        from urllib.parse import quote_plus
        if self.REDIS_PASSWORD:
            return f"redis://:{quote_plus(self.REDIS_PASSWORD)}@{self.REDIS_HOST}:{self.REDIS_PORT}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"

    # ── Cache TTLs (seconds) ─────────────────────────────────────────────────
    CACHE_TTL_HOT: int = 30          # live / high-churn data
    CACHE_TTL_WARM: int = 300        # aggregates, listings
    CACHE_TTL_COLD: int = 3600       # single records, reference data
    CACHE_STALE_GRACE: int = 60      # stale-while-revalidate window

    # ── HTTP fetcher ─────────────────────────────────────────────────────────
    HTTP_TIMEOUT: float = 8.0
    MAX_RETRIES: int = 3
    CONCURRENCY_LIMIT: int = 10

    # ── Scheduler ────────────────────────────────────────────────────────────
    SCHEDULER_ENABLED: bool = True
    REFRESH_INTERVAL_MINUTES: int = 10

    # ── Rate limiting ────────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # ── Trusted proxies ──────────────────────────────────────────────────────
    TRUSTED_PROXY_HEADERS: List[str] = ["X-Forwarded-For", "X-Real-IP"]

    # ── Data sources ─────────────────────────────────────────────────────────
    DATA_SOURCES: List[str] = [
        "https://jsonplaceholder.typicode.com/posts",
        "https://jsonplaceholder.typicode.com/users",
        "https://jsonplaceholder.typicode.com/todos",
        "https://jsonplaceholder.typicode.com/comments",
    ]

    @property
    def DATABASE_URL(self) -> str:
        from urllib.parse import quote_plus
        return (
            f"postgresql+asyncpg://{quote_plus(self.DB_USER)}:{quote_plus(self.DB_PASSWORD)}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
