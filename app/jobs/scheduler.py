"""In-process APScheduler 3.x tick that drains Postgres Job rows (P8-2)."""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db.session import SessionLocal
from app.jobs.handlers import ensure_maintenance_jobs
from app.jobs.runner import process_due_jobs
from app.services.scoring.profile import get_operator_profile

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _tick() -> None:
    session = SessionLocal()
    try:
        process_due_jobs(session, limit=10)
        session.commit()
    except Exception:
        logger.exception("scheduler tick failed")
        session.rollback()
    finally:
        session.close()


def start_scheduler() -> BackgroundScheduler | None:
    """Start the background scheduler if enabled in settings and operator profile."""
    global _scheduler
    settings = get_settings()
    profile = get_operator_profile()
    if not settings.scheduler_enabled or not profile.outreach.scheduler_enabled:
        logger.info("scheduler disabled")
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    session = SessionLocal()
    try:
        ensure_maintenance_jobs(session)
        session.commit()
    except Exception:
        logger.exception("failed to seed maintenance jobs")
        session.rollback()
    finally:
        session.close()

    tick_seconds = max(15, profile.outreach.scheduler_tick_seconds)
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        _tick,
        trigger=IntervalTrigger(seconds=tick_seconds),
        id="prospectiq_job_tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info("APScheduler started (tick=%ss)", tick_seconds)
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped")


def scheduler_status() -> dict[str, Any]:
    running = bool(_scheduler is not None and _scheduler.running)
    return {
        "running": running,
        "enabled": get_settings().scheduler_enabled
        and get_operator_profile().outreach.scheduler_enabled,
    }
