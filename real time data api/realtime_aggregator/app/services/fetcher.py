from __future__ import annotations

import asyncio
import time
import httpx
import structlog

from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type,
)
from app.config import settings
from app.exceptions import FetchError, CircuitOpenError

log = structlog.get_logger(__name__)

# ── Per-source circuit breaker state ─────────────────────────────────────────
# Simple in-process breaker; replace with Redis-backed for multi-worker setups.

_circuit_lock = asyncio.Lock()
_circuit: dict[str, dict] = {}
FAILURE_THRESHOLD = 3
RECOVERY_SECONDS = 60


async def _is_open(url: str) -> bool:
    async with _circuit_lock:
        state = _circuit.get(url)
        if not state:
            return False
        if state["failures"] >= FAILURE_THRESHOLD:
            if time.monotonic() - state["opened_at"] < RECOVERY_SECONDS:
                return True
            # Half-open: allow one probe
            state["failures"] = FAILURE_THRESHOLD - 1
        return False


async def _record_failure(url: str) -> None:
    async with _circuit_lock:
        state = _circuit.setdefault(url, {"failures": 0, "opened_at": 0.0})
        state["failures"] += 1
        if state["failures"] >= FAILURE_THRESHOLD:
            state["opened_at"] = time.monotonic()
            log.warning("circuit.opened", url=url)


async def _record_success(url: str) -> None:
    async with _circuit_lock:
        _circuit.pop(url, None)


async def circuit_status() -> dict:
    async with _circuit_lock:
        return {
            url: {
                "failures": s["failures"],
                "open": s["failures"] >= FAILURE_THRESHOLD,
            }
            for url, s in _circuit.items()
        }


# ── Core fetch ────────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    stop=stop_after_attempt(settings.MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _fetch_one(client: httpx.AsyncClient, url: str) -> tuple[list, int]:
    t0 = time.monotonic()
    resp = await client.get(url, timeout=settings.HTTP_TIMEOUT)
    resp.raise_for_status()
    ms = int((time.monotonic() - t0) * 1000)
    data = resp.json()
    return (data if isinstance(data, list) else [data]), ms


async def fetch_sources(urls: list[str]) -> list[dict]:
    sem = asyncio.Semaphore(settings.CONCURRENCY_LIMIT)

    async def _guarded(client: httpx.AsyncClient, url: str) -> dict:
        source_key = url.rstrip("/").rsplit("/", 1)[-1]
        if await _is_open(url):
            log.warning("circuit.rejected", url=url)
            return {
                "url": url, "source_key": source_key,
                "records": [], "duration_ms": 0,
                "error": "Circuit open — upstream unavailable",
            }

        async with sem:
            try:
                records, ms = await _fetch_one(client, url)
                await _record_success(url)
                log.info("fetch.ok", source=source_key, records=len(records), ms=ms)
                return {
                    "url": url, "source_key": source_key,
                    "records": records, "duration_ms": ms, "error": None,
                }
            except Exception as exc:
                await _record_failure(url)
                log.error("fetch.failed", source=source_key, error=str(exc))
                return {
                    "url": url, "source_key": source_key,
                    "records": [], "duration_ms": 0, "error": str(exc),
                }

    limits = httpx.Limits(max_connections=settings.CONCURRENCY_LIMIT, max_keepalive_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        return list(await asyncio.gather(*[_guarded(client, u) for u in urls]))
