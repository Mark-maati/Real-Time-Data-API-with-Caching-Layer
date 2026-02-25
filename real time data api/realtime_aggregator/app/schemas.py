from __future__ import annotations
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class SourceResult(BaseModel):
    source_key: str
    source_url: str
    record_count: int
    last_fetch: Optional[datetime] = None
    duration_ms: int
    status: str


class AggregateResponse(BaseModel):
    total_records: int
    sources: List[SourceResult]
    aggregated_at: datetime
    cache_status: Optional[str] = None     # HIT | MISS | STALE


class RecordOut(BaseModel):
    id: int
    source_key: str
    external_id: Optional[int]
    payload: Any
    checksum: Optional[str]
    fetched_at: datetime
    model_config = {"from_attributes": True}


class PaginatedRecords(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[RecordOut]


class AuditOut(BaseModel):
    id: int
    source_url: str
    source_key: str
    status: str
    records_fetched: int
    records_changed: int
    duration_ms: Optional[int]
    error_detail: Optional[str]
    triggered_by: str
    created_at: datetime
    model_config = {"from_attributes": True}


class RefreshResponse(BaseModel):
    message: str
    sources_refreshed: int
    records_upserted: int
    records_changed: int = 0
    errors: List[str]


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    scheduler: str
    version: str


class MetricsResponse(BaseModel):
    cache_hits: int
    cache_misses: int
    stale_hits: int
    hit_rate: float
    total_requests: int
    circuit_breakers: dict
