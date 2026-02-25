from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import build_key, cache_get, cache_set, invalidate_pattern, record_hit, record_miss
from app.config import settings
from app.database import SessionLocal
from app.repositories.audits import AuditRepository
from app.repositories.records import RecordRepository
from app.schemas import AggregateResponse, RefreshResponse, SourceResult
from app.services.fetcher import fetch_sources

log = structlog.get_logger(__name__)


async def refresh_data(db: AsyncSession, triggered_by: str = "manual") -> RefreshResponse:
    record_repo = RecordRepository(db)
    audit_repo = AuditRepository(db)

    raw_results = await fetch_sources(settings.DATA_SOURCES)

    total_upserted, total_changed, errors = 0, 0, []

    for result in raw_results:
        if result["error"]:
            errors.append(f"{result['source_key']}: {result['error']}")
            await audit_repo.log(
                source_url=result["url"],
                source_key=result["source_key"],
                status="error",
                error_detail=result["error"],
                triggered_by=triggered_by,
            )
            continue

        fetched, changed = await record_repo.upsert_source(
            result["source_key"], result["url"], result["records"]
        )
        await audit_repo.log(
            source_url=result["url"],
            source_key=result["source_key"],
            status="ok",
            records_fetched=fetched,
            records_changed=changed,
            duration_ms=result["duration_ms"],
            triggered_by=triggered_by,
        )
        total_upserted += fetched
        total_changed += changed

    await db.commit()
    await invalidate_pattern("agg:v2:*")
    log.info("refresh.complete", upserted=total_upserted, changed=total_changed, errors=len(errors))

    return RefreshResponse(
        message="Refresh complete",
        sources_refreshed=len([r for r in raw_results if not r["error"]]),
        records_upserted=total_upserted,
        records_changed=total_changed,
        errors=errors,
    )


async def _revalidate_aggregate(key: str) -> None:
    """Background revalidation for stale aggregate cache entries."""
    try:
        async with SessionLocal() as db:
            summaries = await RecordRepository(db).source_summary()
            sources = [
                SourceResult(
                    source_key=r["source_key"],
                    source_url=r["source_url"],
                    record_count=r["cnt"],
                    last_fetch=r["last_fetch"],
                    duration_ms=0,
                    status="ok",
                )
                for r in summaries
            ]
            response = AggregateResponse(
                total_records=sum(s.record_count for s in sources),
                sources=sources,
                aggregated_at=datetime.now(timezone.utc),
                cache_status="MISS",
            )
            await cache_set(key, response.model_dump(), settings.CACHE_TTL_WARM)
            log.info("cache.revalidated", key=key)
    except Exception as exc:
        log.error("cache.revalidation.failed", key=key, error=str(exc))


async def get_aggregate_summary(db: AsyncSession) -> AggregateResponse:
    key = build_key("aggregate_summary")
    value, is_stale = await cache_get(key)

    if value and not is_stale:
        await record_hit()
        value["cache_status"] = "HIT"
        return AggregateResponse(**value)

    if value and is_stale:
        await record_hit(stale=True)
        log.info("cache.stale_hit", key=key)
        # Trigger background revalidation
        asyncio.create_task(_revalidate_aggregate(key))
        value["cache_status"] = "STALE"
        return AggregateResponse(**value)

    await record_miss()
    summaries = await RecordRepository(db).source_summary()
    sources = [
        SourceResult(
            source_key=r["source_key"],
            source_url=r["source_url"],
            record_count=r["cnt"],
            last_fetch=r["last_fetch"],
            duration_ms=0,
            status="ok",
        )
        for r in summaries
    ]
    response = AggregateResponse(
        total_records=sum(s.record_count for s in sources),
        sources=sources,
        aggregated_at=datetime.now(timezone.utc),
        cache_status="MISS",
    )
    await cache_set(key, response.model_dump(), settings.CACHE_TTL_WARM)
    return response
