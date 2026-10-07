"""Background job package."""

from app.jobs.queue import enqueue_job

__all__ = ["enqueue_job"]
