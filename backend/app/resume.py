"""Automatic resume for DVD ripping jobs interrupted by server restarts."""
import logging
from datetime import datetime
from typing import List

from sqlmodel import select

from app.database import RipJob, get_session_context

logger = logging.getLogger(__name__)

# Jobs that were actively in progress when the worker/server died.
# "queued" is intentionally excluded: Celery with a persistent Redis broker
# already owns those tasks, so re-queueing them would create duplicates.
RESUMABLE_STATUSES = {
    "analyzing",
    "ripping",
    "transcoding",
    "fetching_metadata",
    "archiving",
}


def _get_interrupted_jobs() -> List[RipJob]:
    """Fetch RipJob rows that were in-flight when the server stopped."""
    with get_session_context() as session:
        statement = select(RipJob).where(RipJob.status.in_(RESUMABLE_STATUSES))
        return list(session.exec(statement).all())


def _requeue_job(job: RipJob) -> None:
    """Re-queue an interrupted job by reusing its existing RipJob record."""
    # Import here to avoid circular imports at module load time.
    from app.tasks import process_dvd_task

    logger.warning(
        "Resuming interrupted job %d (was %s, progress %d%%)",
        job.id,
        job.status,
        job.progress_percent,
    )

    task = process_dvd_task.delay(
        device_path=job.device_path,
        disc_label=job.source_disc_title,
        existing_job_id=job.id,
    )

    with get_session_context() as session:
        refreshed = session.get(RipJob, job.id)
        refreshed.celery_task_id = task.id
        refreshed.status = "queued"
        refreshed.progress_percent = 0
        refreshed.current_step = "Resumed after restart - waiting to start"
        refreshed.step_details = ""
        refreshed.resumed = True
        refreshed.resumed_at = datetime.utcnow()
        refreshed.completed_at = None
        refreshed.error_message = None
        session.add(refreshed)
        session.commit()

    logger.info("Re-queued job %d as Celery task %s", job.id, task.id)


def resume_interrupted_jobs() -> int:
    """Re-queue any DVD ripping jobs that were interrupted by a restart.

    Returns the number of jobs that were resumed.
    """
    try:
        jobs = _get_interrupted_jobs()
    except Exception:
        logger.exception("Failed to query interrupted jobs; skipping resume")
        return 0

    if not jobs:
        logger.info("No interrupted jobs found; nothing to resume")
        return 0

    resumed_count = 0
    for job in jobs:
        try:
            _requeue_job(job)
            resumed_count += 1
        except Exception:
            logger.exception("Failed to resume job %d", job.id)

    logger.info("Resumed %d of %d interrupted job(s)", resumed_count, len(jobs))
    return resumed_count
