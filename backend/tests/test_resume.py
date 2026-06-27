"""Tests for automatic job resume after server restart."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlmodel import Session, select

from app.database import RipJob, get_session_context
from app.resume import RESUMABLE_STATUSES, resume_interrupted_jobs


def _create_job(session: Session, status: str, title: str = "Test Disc") -> RipJob:
    """Helper to create a RipJob in a given status."""
    job = RipJob(
        device_path="/dev/sr0",
        source_disc_title=title,
        status=status,
        progress_percent=42,
        current_step="Some step",
        started_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_resumes_only_interrupted_jobs():
    """Only in-flight jobs are re-queued; terminal/queued jobs are left alone."""
    # Clear any existing data and create test jobs.
    with get_session_context() as session:
        for job in session.exec(select(RipJob)).all():
            session.delete(job)
        session.commit()

    with get_session_context() as session:
        ripping = _create_job(session, "ripping", "Resumable")
        transcoding = _create_job(session, "transcoding", "Resumable2")
        queued = _create_job(session, "queued", "QueuedDisc")
        completed = _create_job(session, "completed", "DoneDisc")
        error = _create_job(session, "error", "ErrorDisc")
        cancelled = _create_job(session, "cancelled", "CancelledDisc")

        # Keep plain IDs; the ORM instances are bound to the closed session above.
        ripping_id = ripping.id
        transcoding_id = transcoding.id
        queued_id = queued.id
        completed_id = completed.id
        error_id = error.id
        cancelled_id = cancelled.id

    mock_task = MagicMock()
    mock_task.id = "new-celery-task-id"

    with patch("app.tasks.process_dvd_task") as mock_process:
        mock_process.delay.return_value = mock_task
        resumed = resume_interrupted_jobs()

    assert resumed == 2
    assert mock_process.delay.call_count == 2

    # Verify resumed jobs are reset to queued and marked resumed.
    with get_session_context() as session:
        ripping = session.get(RipJob, ripping_id)
        transcoding = session.get(RipJob, transcoding_id)

        assert ripping.status == "queued"
        assert ripping.resumed is True
        assert ripping.resumed_at is not None
        assert ripping.celery_task_id == "new-celery-task-id"
        assert ripping.error_message is None

        assert transcoding.status == "queued"
        assert transcoding.resumed is True

        # Queued job is not touched.
        queued = session.get(RipJob, queued_id)
        assert queued.status == "queued"
        assert queued.resumed is False

        # Terminal jobs are not touched.
        assert session.get(RipJob, completed_id).status == "completed"
        assert session.get(RipJob, error_id).status == "error"
        assert session.get(RipJob, cancelled_id).status == "cancelled"


def test_resume_passes_existing_job_id():
    """The resumed Celery task is given the existing job id."""
    with get_session_context() as session:
        for job in session.exec(select(RipJob)).all():
            session.delete(job)
        session.commit()

    with get_session_context() as session:
        job = _create_job(session, "ripping", "PassIdDisc")

    mock_task = MagicMock()
    mock_task.id = "task-id-for-resume"

    with patch("app.tasks.process_dvd_task") as mock_process:
        mock_process.delay.return_value = mock_task
        resume_interrupted_jobs()

    mock_process.delay.assert_called_once_with(
        device_path="/dev/sr0",
        disc_label="PassIdDisc",
        existing_job_id=job.id,
    )


def test_resume_is_safe_when_no_interrupted_jobs():
    """Resume does nothing when there are no interrupted jobs."""
    with get_session_context() as session:
        for job in session.exec(select(RipJob)).all():
            session.delete(job)
        session.commit()

    with patch("app.tasks.process_dvd_task") as mock_process:
        resumed = resume_interrupted_jobs()

    assert resumed == 0
    mock_process.delay.assert_not_called()


def test_resumable_statuses():
    """Ensure the expected statuses are considered resumable."""
    assert RESUMABLE_STATUSES == {
        "analyzing",
        "ripping",
        "transcoding",
        "fetching_metadata",
        "archiving",
    }
