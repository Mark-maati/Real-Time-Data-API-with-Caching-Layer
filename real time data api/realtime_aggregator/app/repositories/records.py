from __future__ import annotations

import hashlib
import json
from typing import List, Optional, Tuple

from sqlalchemy import select, delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataRecord
from app.schemas import RecordOut


class RecordRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _checksum(self, payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

    async def upsert_source(
        self, source_key: str, source_url: str, records: List[dict]
    ) -> Tuple[int, int]:
        """
        Returns (total_records, changed_records).
        Only updates a row when the payload checksum actually changed.
        """
        existing = {
            row.external_id: row
            for row in (
                await self.db.execute(
                    select(DataRecord).where(DataRecord.source_key == source_key)
                )
            ).scalars().all()
        }

        to_insert, changed = [], 0

        for r in records:
            ext_id = r.get("id") if isinstance(r, dict) else None
            checksum = self._checksum(r) if isinstance(r, dict) else ""

            if ext_id and ext_id in existing:
                row = existing[ext_id]
                if row.checksum != checksum:
                    row.payload = r
                    row.checksum = checksum
                    changed += 1
            else:
                to_insert.append(
                    DataRecord(
                        source_key=source_key,
                        source_url=source_url,
                        external_id=ext_id,
                        payload=r,
                        checksum=checksum,
                    )
                )
                changed += 1

        self.db.add_all(to_insert)
        # Remove stale records no longer in the upstream response
        if existing:
            incoming_ids = {r.get("id") for r in records if isinstance(r, dict) and r.get("id")}
            stale = [eid for eid in existing if eid not in incoming_ids]
            if stale:
                await self.db.execute(
                    delete(DataRecord).where(
                        DataRecord.source_key == source_key,
                        DataRecord.external_id.in_(stale),
                    )
                )

        await self.db.flush()
        return len(records), changed

    async def get_paginated(
        self,
        source_key: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[int, List[DataRecord]]:
        base = select(DataRecord)
        count_q = select(func.count(DataRecord.id))
        if source_key:
            base = base.where(DataRecord.source_key == source_key)
            count_q = count_q.where(DataRecord.source_key == source_key)

        total = (await self.db.execute(count_q)).scalar_one()
        rows = (
            await self.db.execute(
                base.order_by(DataRecord.fetched_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
            )
        ).scalars().all()
        return total, list(rows)

    async def get_by_id(self, record_id: int) -> Optional[DataRecord]:
        return await self.db.get(DataRecord, record_id)

    async def source_summary(self) -> List[dict]:
        rows = await self.db.execute(
            select(
                DataRecord.source_key,
                DataRecord.source_url,
                func.count(DataRecord.id).label("cnt"),
                func.max(DataRecord.fetched_at).label("last_fetch"),
            ).group_by(DataRecord.source_key, DataRecord.source_url)
        )
        return [r._asdict() for r in rows.all()]
