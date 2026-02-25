from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import SessionLocal

log = structlog.get_logger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def _scheduled_refresh() -> None:
    from app.services.aggregator import refresh_data
    async with SessionLocal() as db:
        try:
            result = await refresh_data(db, triggered_by="scheduler")
            log.info(
                "scheduler.refresh.done",
                upserted=result.records_upserted,
                changed=result.records_changed,
            )
        except Exception as exc:
            log.error("scheduler.refresh.failed", error=str(exc))


def start_scheduler() -> None:
    global _scheduler
    if not settings.SCHEDULER_ENABLED:
        log.info("scheduler.disabled")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _scheduled_refresh,
        trigger=IntervalTrigger(minutes=settings.REFRESH_INTERVAL_MINUTES),
        id="auto_refresh",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    log.info("scheduler.started", interval_minutes=settings.REFRESH_INTERVAL_MINUTES)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
