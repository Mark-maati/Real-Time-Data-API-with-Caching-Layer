from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


# ── Typed domain exceptions ───────────────────────────────────────────────────

class AppError(Exception):
    """Base for all application-level errors."""
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, detail: str, context: Optional[Dict[str, Any]] = None):
        self.detail = detail
        self.context = context or {}
        super().__init__(detail)


class NotFoundError(AppError):
    status_code = 404
    error_code = "NOT_FOUND"


class FetchError(AppError):
    status_code = 502
    error_code = "UPSTREAM_FETCH_FAILED"


class CacheError(AppError):
    status_code = 503
    error_code = "CACHE_UNAVAILABLE"


class RateLimitError(AppError):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"


class CircuitOpenError(AppError):
    status_code = 503
    error_code = "CIRCUIT_OPEN"


# ── FastAPI exception handlers ────────────────────────────────────────────────

async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "detail": exc.detail,
            "context": exc.context,
        },
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP_ERROR",
            "detail": exc.detail,
        },
    )
