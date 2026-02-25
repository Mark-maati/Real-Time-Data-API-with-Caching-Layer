from __future__ import annotations

import asyncio
import time

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

log = structlog.get_logger(__name__)

# ── In-process rate limiter with periodic cleanup ──────────────────────────────
_lock = asyncio.Lock()
_buckets: dict[str, dict] = {}
_CLEANUP_INTERVAL = 300  # purge stale entries every 5 minutes
_last_cleanup: float = 0.0


def _resolve_client_ip(request: Request) -> str:
    for header in settings.TRUSTED_PROXY_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global _last_cleanup
        client_ip = _resolve_client_ip(request)
        now = time.monotonic()

        async with _lock:
            # Periodic cleanup of stale entries to prevent memory leak
            if now - _last_cleanup > _CLEANUP_INTERVAL:
                stale_ips = [
                    ip for ip, b in _buckets.items()
                    if now - b["window_start"] > settings.RATE_LIMIT_WINDOW_SECONDS * 2
                ]
                for ip in stale_ips:
                    del _buckets[ip]
                _last_cleanup = now

            bucket = _buckets.get(client_ip)
            if bucket is None or now - bucket["window_start"] > settings.RATE_LIMIT_WINDOW_SECONDS:
                _buckets[client_ip] = {"window_start": now, "count": 1}
            else:
                bucket["count"] += 1

            count = _buckets[client_ip]["count"]
            window_start = _buckets[client_ip]["window_start"]

        remaining = max(0, settings.RATE_LIMIT_REQUESTS - count)
        reset_at = int(window_start + settings.RATE_LIMIT_WINDOW_SECONDS - now)

        if count > settings.RATE_LIMIT_REQUESTS:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "RATE_LIMIT_EXCEEDED",
                    "detail": (
                        f"Too many requests. Limit: {settings.RATE_LIMIT_REQUESTS} "
                        f"per {settings.RATE_LIMIT_WINDOW_SECONDS}s"
                    ),
                },
                headers={
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(max(0, reset_at)),
                    "Retry-After": str(max(0, reset_at)),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(max(0, reset_at))
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=ms,
            client=_resolve_client_ip(request),
        )
        response.headers["X-Response-Time-Ms"] = str(ms)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        if not settings.DEBUG:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
