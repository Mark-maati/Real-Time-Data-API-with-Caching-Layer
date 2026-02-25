from __future__ import annotations

import json
import hashlib
import asyncio
import time
from typing import Any, Optional, Tuple
from contextlib import asynccontextmanager

from redis.asyncio import Redis, ConnectionPool, from_url
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import RedisError

import structlog
from app.config import settings
from app.exceptions import CacheError

log = structlog.get_logger(__name__)

_pool: Optional[ConnectionPool] = None


# ── Pool lifecycle ────────────────────────────────────────────────────────────

async def init_redis_pool() -> None:
    global _pool
    _pool = ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=settings.REDIS_POOL_SIZE,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
        decode_responses=True,
        retry=Retry(ExponentialBackoff(), retries=3),
        retry_on_error=[RedisError],
    )
    log.info("redis.pool.initialized", pool_size=settings.REDIS_POOL_SIZE)


async def close_redis_pool() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
        log.info("redis.pool.closed")


def get_redis() -> Redis:
    if _pool is None:
        raise CacheError("Redis pool not initialized")
    return Redis(connection_pool=_pool)


async def ping_redis() -> bool:
    try:
        r = get_redis()
        return await r.ping()
    except Exception:
        return False


# ── Key builder ───────────────────────────────────────────────────────────────

def build_key(*parts: Any) -> str:
    raw = ":".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    slug = raw[:60].replace(" ", "_")
    return f"agg:v2:{digest}:{slug}"


# ── Stale-while-revalidate primitives ────────────────────────────────────────
#
# We store two keys per logical entry:
#   <key>         → the actual payload
#   <key>:stale   → sentinel that expires CACHE_STALE_GRACE seconds later
#
# Callers check (value, is_stale). When stale, serve the old value
# immediately and trigger a background revalidation.

async def cache_get(key: str) -> Tuple[Optional[Any], bool]:
    """
    Returns (value, is_stale).
    value=None means total cache miss.
    is_stale=True means value exists but is beyond its primary TTL.
    """
    try:
        r = get_redis()
        pipe = r.pipeline()
        await pipe.get(key)
        await pipe.exists(f"{key}:fresh")
        value_raw, is_fresh = await pipe.execute()

        if value_raw is None:
            return None, False

        return json.loads(value_raw), not bool(is_fresh)
    except RedisError as e:
        log.warning("cache.get.error", key=key, error=str(e))
        return None, False


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """
    Stores value with TTL, plus a :fresh sentinel with the same TTL.
    The raw value lingers an extra STALE_GRACE window for SWR reads.
    """
    try:
        r = get_redis()
        stale_ttl = ttl + settings.CACHE_STALE_GRACE
        serialized = json.dumps(value, default=str)
        pipe = r.pipeline()
        await pipe.setex(key, stale_ttl, serialized)
        await pipe.setex(f"{key}:fresh", ttl, "1")
        await pipe.execute()
    except RedisError as e:
        log.warning("cache.set.error", key=key, error=str(e))


async def cache_delete(key: str) -> None:
    try:
        r = get_redis()
        await r.delete(key, f"{key}:fresh")
    except RedisError as e:
        log.warning("cache.delete.error", key=key, error=str(e))


async def invalidate_pattern(pattern: str) -> int:
    """Use SCAN instead of KEYS to avoid blocking Redis."""
    try:
        r = get_redis()
        deleted = 0
        async for key in r.scan_iter(match=pattern, count=100):
            await r.delete(key)
            deleted += 1
        if deleted:
            log.info("cache.invalidated", pattern=pattern, count=deleted)
        return deleted
    except RedisError as e:
        log.warning("cache.invalidate.error", pattern=pattern, error=str(e))
        return 0


# ── Stats (thread-safe via asyncio.Lock) ──────────────────────────────────────

_stats_lock = asyncio.Lock()
_stats = {"hits": 0, "misses": 0, "stale_hits": 0}


async def record_hit(stale: bool = False) -> None:
    async with _stats_lock:
        if stale:
            _stats["stale_hits"] += 1
        else:
            _stats["hits"] += 1


async def record_miss() -> None:
    async with _stats_lock:
        _stats["misses"] += 1


async def get_cache_stats() -> dict:
    async with _stats_lock:
        total = _stats["hits"] + _stats["misses"] + _stats["stale_hits"]
        hit_rate = round((_stats["hits"] + _stats["stale_hits"]) / total, 4) if total else 0.0
        return {**_stats, "total_requests": total, "hit_rate": hit_rate}
