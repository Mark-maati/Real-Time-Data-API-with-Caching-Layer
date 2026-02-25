from __future__ import annotations
from fastapi import APIRouter, Depends
import sqlalchemy

from app.auth import require_api_key
from app.cache import invalidate_pattern, get_cache_stats, ping_redis
from app.schemas import HealthResponse, MetricsResponse
from app.services.fetcher import circuit_status
from app.services.scheduler import _scheduler
from app.config import settings
from app.database import engine

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check is intentionally unauthenticated for load balancer probes."""
    redis_ok = await ping_redis()
    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    sched_status = "running" if (_scheduler and _scheduler.running) else "stopped"

    return HealthResponse(
        status="ok" if (redis_ok and db_status == "ok") else "degraded",
        database=db_status,
        redis="ok" if redis_ok else "error",
        scheduler=sched_status,
        version=settings.APP_VERSION,
    )


@router.get("/metrics", response_model=MetricsResponse, dependencies=[Depends(require_api_key)])
async def metrics():
    stats = await get_cache_stats()
    return MetricsResponse(
        cache_hits=stats["hits"],
        cache_misses=stats["misses"],
        stale_hits=stats["stale_hits"],
        hit_rate=stats["hit_rate"],
        total_requests=stats["total_requests"],
        circuit_breakers=await circuit_status(),
    )


@router.delete("/cache", status_code=204, dependencies=[Depends(require_api_key)])
async def bust_cache():
    await invalidate_pattern("agg:v2:*")


@router.get("/sources", dependencies=[Depends(require_api_key)])
async def list_sources():
    return {"sources": settings.DATA_SOURCES, "count": len(settings.DATA_SOURCES)}
