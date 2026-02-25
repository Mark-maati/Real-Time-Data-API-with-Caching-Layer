from __future__ import annotations
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import FetchAudit


class AuditRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        source_url: str,
        source_key: str,
        status: str,
        records_fetched: int = 0,
        records_changed: int = 0,
        duration_ms: int = 0,
        error_detail: str | None = None,
        triggered_by: str = "manual",
    ) -> None:
        self.db.add(
            FetchAudit(
                source_url=source_url,
                source_key=source_key,
                status=status,
                records_fetched=records_fetched,
                records_changed=records_changed,
                duration_ms=duration_ms,
                error_detail=error_detail,
                triggered_by=triggered_by,
            )
        )

    async def recent(self, limit: int = 50) -> List[FetchAudit]:
        rows = await self.db.execute(
            select(FetchAudit)
            .order_by(FetchAudit.created_at.desc())
            .limit(limit)
        )
        return rows.scalars().all()
