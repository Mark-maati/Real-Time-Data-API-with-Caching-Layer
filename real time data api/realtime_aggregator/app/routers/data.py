from __future__ import annotations
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_key
from app.cache import build_key, cache_get, cache_set, record_hit, record_miss
from app.config import settings
from app.database import get_db, SessionLocal
from app.exceptions import NotFoundError
from app.repositories.audits import AuditRepository
from app.repositories.records import RecordRepository
from app.schemas import (
    AggregateResponse, AuditOut, PaginatedRecords,
    RecordOut, RefreshResponse,
)
from app.services.aggregator import get_aggregate_summary, refresh_data

router = APIRouter(prefix="/api/v1", tags=["data"], dependencies=[Depends(require_api_key)])


@router.post("/refresh", response_model=RefreshResponse, status_code=202)
async def trigger_refresh_async():
    """Fire-and-forget refresh using its own DB session."""
    import asyncio

    async def _bg_refresh() -> None:
        async with SessionLocal() as db:
            await refresh_data(db, triggered_by="manual")

    asyncio.create_task(_bg_refresh())
    return RefreshResponse(
        message="Refresh triggered in background",
        sources_refreshed=0, records_upserted=0, records_changed=0, errors=[]
    )


@router.post("/refresh/sync", response_model=RefreshResponse)
async def trigger_refresh_sync(db: AsyncSession = Depends(get_db)):
    """Blocking refresh — awaits completion. Handy for CI/testing."""
    return await refresh_data(db, triggered_by="manual")


@router.get("/aggregate", response_model=AggregateResponse)
async def aggregate(db: AsyncSession = Depends(get_db)):
    return await get_aggregate_summary(db)


@router.get("/records", response_model=PaginatedRecords)
async def list_records(
    source_key: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    cache_key = build_key("records", source_key, page, page_size)
    value, is_stale = await cache_get(cache_key)
    if value and not is_stale:
        await record_hit()
        return PaginatedRecords(**value)

    await record_miss()
    repo = RecordRepository(db)
    total, rows = await repo.get_paginated(source_key, page, page_size)
    result = PaginatedRecords(
        total=total, page=page, page_size=page_size,
        items=[RecordOut.model_validate(r) for r in rows],
    )
    await cache_set(cache_key, result.model_dump(), settings.CACHE_TTL_WARM)
    return result


@router.get("/records/{record_id}", response_model=RecordOut)
async def get_record(record_id: int, db: AsyncSession = Depends(get_db)):
    cache_key = build_key("record", record_id)
    value, is_stale = await cache_get(cache_key)
    if value and not is_stale:
        await record_hit()
        return RecordOut(**value)

    await record_miss()
    row = await RecordRepository(db).get_by_id(record_id)
    if not row:
        raise NotFoundError(f"Record {record_id} not found")

    out = RecordOut.model_validate(row)
    await cache_set(cache_key, out.model_dump(), settings.CACHE_TTL_COLD)
    return out


@router.get("/logs", response_model=List[AuditOut])
async def fetch_logs(
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows = await AuditRepository(db).recent(limit)
    return [AuditOut.model_validate(r) for r in rows]
