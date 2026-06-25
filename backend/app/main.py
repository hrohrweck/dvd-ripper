"""FastAPI application main entry point."""
import os
import shutil
import subprocess
import asyncio
import logging
import mimetypes
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks, Request, UploadFile, File, Header
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
from celery.result import AsyncResult

from app.config import get_settings, Settings, update_settings
from app.database import (
    create_db_and_tables, get_session, DVDEntry, RipJob, User,
    get_all_dvds, get_dvd_by_id, get_active_jobs, get_job_by_id,
    get_session_context
)
from app.auth import (
    authenticate_user, create_access_token, verify_token, 
    create_default_admin, get_password_hash, is_first_run
)
from app.ripper import DVDRipper
from app.dvd_monitor import create_monitor, DiscInfo
from app.metadata.fetcher import MetadataFetcher
from app.tasks import process_dvd_task, celery_app
from app.duplicate_checker import duplicate_checker
from app.log_viewer import log_viewer
from app.job_manager import job_manager

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token", auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    create_db_and_tables()
    
    # Check first run
    if is_first_run():
        print("First run detected - admin setup required")
        os.environ["FIRST_RUN"] = "true"
    else:
        os.environ["FIRST_RUN"] = "false"
    
    # Start DVD monitor in background
    settings = get_settings()
    monitor = create_monitor(settings.dvd_device)
    
    async def on_disc_inserted(disc_info: DiscInfo):
        """Handle disc insertion."""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Disc inserted callback triggered: {disc_info}")
        if disc_info.is_dvd_video:
            # Check for duplicate before ripping
            logger.info(f"Checking for duplicate: {disc_info.label}")
            duplicate_check = duplicate_checker.check_disc_in_library(
                disc_label=disc_info.label,
                disc_size=disc_info.volume_size
            )
            
            if duplicate_check["is_duplicate"]:
                logger.warning(f"DUPLICATE DVD DETECTED: {disc_info.label}")
                logger.warning(f"Skipping auto-rip: {duplicate_check['message']}")
                # Log the duplicate detection
                duplicate_checker.log_duplicate_detection(
                    disc_info.label, 
                    is_duplicate=True, 
                    message=duplicate_check["message"]
                )
                return
            
            logger.info(f"NEW DVD DETECTED: {disc_info.label}")
            logger.info(f"Auto-triggering rip for DVD: {disc_info.label}")
            # Auto-trigger rip if configured (or queue for manual approval)
            task = process_dvd_task.delay(
                device_path=disc_info.device,
                disc_label=disc_info.label
            )
            logger.info(f"Celery task queued: {task.id}")
        else:
            logger.info(f"Disc is not DVD-Video, skipping auto-rip")
    
    monitor.on_disc_inserted(on_disc_inserted)
    
    # Run monitor in background task
    monitor_task = asyncio.create_task(monitor.start_monitoring())
    
    yield
    
    # Shutdown
    monitor.stop_monitoring()
    monitor_task.cancel()


app = FastAPI(
    title="DVD Ripper",
    description="Automated DVD ripping and archiving system",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependencies
async def get_current_user(token: str = Depends(oauth2_scheme)) -> Optional[str]:
    """Get current user from JWT token."""
    if not token:
        return None
    payload = verify_token(token)
    if payload is None:
        return None
    return payload.get("sub")


async def require_auth(token: str = Depends(oauth2_scheme)) -> str:
    """Require authentication."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload.get("sub")


async def require_auth_query_or_header(
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
) -> str:
    """Require authentication from Bearer header or ?token= query parameter.

    HTML5 video elements cannot send custom headers, so the stream endpoint
    accepts the JWT as a query string token.
    """
    auth_token = token
    if not auth_token and authorization and authorization.lower().startswith("bearer "):
        auth_token = authorization[7:]
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(auth_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload.get("sub")


# Routes

@app.get("/api/status")
async def get_status():
    """Get system status."""
    settings = get_settings()
    return {
        "status": "ok",
        "first_run": is_first_run(),
        "version": "1.0.0",
        "features": {
            "auth_enabled": settings.server.auth_enabled,
            "auto_rip": True
        }
    }


@app.post("/api/setup")
async def initial_setup(
    password: str,
    settings_update: Optional[dict] = None,
    session: Session = Depends(get_session)
):
    """First-run setup endpoint."""
    if not is_first_run():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setup already completed"
        )
    
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters"
        )
    
    # Create admin user
    create_default_admin(password)
    
    # Update settings if provided
    if settings_update:
        update_settings(settings_update)
    
    return {"status": "setup_complete"}


@app.post("/api/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session)
):
    """Login endpoint."""
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": user.username})
    
    # Update last login
    user.last_login = datetime.utcnow()
    session.add(user)
    session.commit()
    
    return {"access_token": access_token, "token_type": "bearer"}


# Library routes

@app.get("/api/library", response_model=List[dict])
async def get_library(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Get DVD library."""
    statement = select(DVDEntry).order_by(DVDEntry.created_at.desc())
    
    if search:
        statement = statement.where(
            DVDEntry.title.contains(search) | 
            DVDEntry.plot.contains(search)
        )
    
    statement = statement.offset(skip).limit(limit)
    entries = session.exec(statement).all()
    
    return [
        {
            "id": e.id,
            "title": e.title,
            "original_title": e.original_title,
            "year": e.year,
            "plot": e.plot,
            "poster_url": e.poster_url,
            "genre": e.genre,
            "runtime": e.runtime,
            "file_path": e.file_path,
            "file_size": e.file_size,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None
        }
        for e in entries
    ]


@app.get("/api/library/{dvd_id}")
async def get_dvd_details(
    dvd_id: int,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Get DVD details."""
    dvd = get_dvd_by_id(session, dvd_id)
    if not dvd:
        raise HTTPException(status_code=404, detail="DVD not found")
    
    return _dvd_entry_to_dict(dvd)


def _delete_archive_file(file_path: str, settings: Settings) -> bool:
    """Delete an archive file from local disk or SSH destination.

    Returns True if the file was deleted or did not exist, False on
    unexpected failure. Errors are logged but not raised so that the
    library entry can still be removed.
    """
    if not file_path:
        return True

    if settings.destination.type == "ssh":
        try:
            import paramiko
            ssh_config = settings.destination.ssh
            host = ssh_config.host
            user = ssh_config.user
            key_path = ssh_config.key_path

            if not host or not user:
                logger.warning("SSH destination not fully configured; skipping remote file deletion")
                return True

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs = {
                "hostname": host,
                "username": user,
                "timeout": 30,
            }
            if key_path and Path(key_path).exists():
                connect_kwargs["key_filename"] = key_path

            client.connect(**connect_kwargs)
            try:
                sftp = client.open_sftp()
                try:
                    sftp.remove(file_path)
                    logger.info(f"Deleted remote archive file: {file_path}")
                except FileNotFoundError:
                    logger.warning(f"Remote archive file already removed: {file_path}")
                finally:
                    sftp.close()
            finally:
                client.close()
            return True
        except Exception as e:
            logger.warning(f"Could not delete remote archive file {file_path}: {e}")
            return False

    # Local destination
    path = Path(file_path)
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        logger.info(f"Deleted local archive file: {file_path}")
        return True
    except Exception as e:
        logger.warning(f"Could not delete local archive file {file_path}: {e}")
        return False


@app.delete("/api/library/{dvd_id}")
async def delete_dvd(
    dvd_id: int,
    delete_file: bool = False,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Delete DVD from library."""
    dvd = get_dvd_by_id(session, dvd_id)
    if not dvd:
        raise HTTPException(status_code=404, detail="DVD not found")

    # Delete the archive file if requested. Do not let a missing or
    # inaccessible file block removal of the library entry.
    if delete_file and dvd.file_path:
        settings = get_settings()
        _delete_archive_file(dvd.file_path, settings)

    # Unlink associated rip jobs so the foreign key never blocks deletion
    # regardless of database configuration.
    jobs = session.exec(select(RipJob).where(RipJob.dvd_entry_id == dvd_id)).all()
    for job in jobs:
        job.dvd_entry_id = None
        session.add(job)

    session.delete(dvd)
    session.commit()

    return {"status": "deleted"}


def _guess_video_mime_type(file_path: Path) -> str:
    """Guess MIME type for common video containers."""
    ext = file_path.suffix.lower()
    mapping = {
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".m4v": "video/mp4",
        ".ts": "video/mp2t",
    }
    return mapping.get(ext, "application/octet-stream")


def _parse_range_header(range_header: Optional[str], file_size: int) -> Optional[tuple[int, int]]:
    """Parse a single 'bytes=start-end' range. Returns (start, end) or None."""
    if not range_header or not range_header.lower().startswith("bytes="):
        return None
    range_spec = range_header[6:].strip()
    if "," in range_spec:
        # Multipart ranges are not supported for this endpoint
        return None
    try:
        start_str, end_str = range_spec.split("-")
        start = int(start_str) if start_str else None
        end = int(end_str) if end_str else None
    except ValueError:
        return None

    if start is None:
        # Suffix range: last N bytes
        suffix = end if end is not None else 0
        start = max(0, file_size - suffix)
        end = file_size - 1
    else:
        if end is None or end >= file_size:
            end = file_size - 1
        if start > end or start >= file_size:
            return None

    return start, end


CHUNK_SIZE = 1024 * 1024  # 1 MB


@app.get("/api/library/{dvd_id}/stream")
async def stream_dvd(
    dvd_id: int,
    request: Request,
    token: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth_query_or_header)
):
    """Stream the archived video file for a library entry.

    Supports HTTP range requests so the browser can seek and buffer
    efficiently without stuttering.
    """
    dvd = get_dvd_by_id(session, dvd_id)
    if not dvd:
        raise HTTPException(status_code=404, detail="DVD not found")

    if not dvd.file_path:
        raise HTTPException(status_code=404, detail="No file path for this entry")

    settings = get_settings()
    archive_base = Path(settings.destination.local.path).resolve()
    file_path = Path(dvd.file_path).resolve()

    # Path traversal protection: the resolved file must be inside the archive
    try:
        file_path.relative_to(archive_base)
    except ValueError:
        logger.warning(f"Stream request attempted outside archive: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists() or not file_path.is_file():
        logger.warning(f"Stream request file not found: {file_path}")
        raise HTTPException(status_code=404, detail="Video file not found")

    media_type = _guess_video_mime_type(file_path)
    file_size = file_path.stat().st_size
    logger.info(
        f"Streaming {file_path} ({file_size} bytes, {media_type}) to user {current_user}"
    )
    range_tuple = _parse_range_header(request.headers.get("range"), file_size)

    if range_tuple:
        start, end = range_tuple
        length = end - start + 1

        def iter_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        logger.debug(
            f"Stream range request for {file_path}: bytes {start}-{end}/{file_size}"
        )
        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
                "Accept-Ranges": "bytes",
            }
        )

    def iter_full():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    logger.debug(f"Stream full request for {file_path}: {file_size} bytes")
    return StreamingResponse(
        iter_full(),
        status_code=200,
        media_type=media_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        }
    )


class DVDUpdate(BaseModel):
    """Editable fields for a library entry."""
    title: Optional[str] = None
    original_title: Optional[str] = None
    year: Optional[int] = None
    plot: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    genre: Optional[str] = None
    director: Optional[str] = None
    cast: Optional[List[str]] = None
    runtime: Optional[int] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[int] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    status: Optional[str] = None
    error_message: Optional[str] = None


def _dvd_entry_to_dict(dvd: DVDEntry) -> dict:
    """Serialize a DVDEntry to the same shape used by the GET endpoints."""
    return {
        "id": dvd.id,
        "title": dvd.title,
        "original_title": dvd.original_title,
        "year": dvd.year,
        "plot": dvd.plot,
        "poster_url": dvd.poster_url,
        "backdrop_url": dvd.backdrop_url,
        "genre": dvd.genre,
        "director": dvd.director,
        "cast": dvd.cast.split(", ") if dvd.cast else [],
        "runtime": dvd.runtime,
        "imdb_id": dvd.imdb_id,
        "tmdb_id": dvd.tmdb_id,
        "file_path": dvd.file_path,
        "file_size": dvd.file_size,
        "file_format": dvd.file_format,
        "video_codec": dvd.video_codec,
        "audio_codec": dvd.audio_codec,
        "resolution": dvd.resolution,
        "status": dvd.status,
        "error_message": dvd.error_message,
        "created_at": dvd.created_at.isoformat() if dvd.created_at else None
    }


@app.put("/api/library/{dvd_id}")
async def update_dvd(
    dvd_id: int,
    update: DVDUpdate,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Update metadata for a library entry."""
    dvd = get_dvd_by_id(session, dvd_id)
    if not dvd:
        raise HTTPException(status_code=404, detail="DVD not found")
    
    update_data = update.model_dump(exclude_unset=True)
    
    # Convert list fields to comma-separated strings for storage
    if "cast" in update_data and isinstance(update_data["cast"], list):
        update_data["cast"] = ", ".join(update_data["cast"])
    if "genre" in update_data and isinstance(update_data["genre"], list):
        update_data["genre"] = ", ".join(update_data["genre"])
    
    # Only allow known fields
    allowed_fields = set(DVDUpdate.model_fields.keys())
    for field, value in update_data.items():
        if field in allowed_fields:
            setattr(dvd, field, value)
    
    dvd.updated_at = datetime.utcnow()
    session.add(dvd)
    session.commit()
    session.refresh(dvd)
    
    return _dvd_entry_to_dict(dvd)


class RefetchRequest(BaseModel):
    """Request body for refetching metadata from a provider."""
    provider: str
    item_id: str


@app.post("/api/library/{dvd_id}/refetch-metadata")
async def refetch_dvd_metadata(
    dvd_id: int,
    request: RefetchRequest,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Fetch metadata from an online provider and update the library entry."""
    dvd = get_dvd_by_id(session, dvd_id)
    if not dvd:
        raise HTTPException(status_code=404, detail="DVD not found")
    
    settings = get_settings()
    fetcher = MetadataFetcher(settings)
    details = await fetcher.get_details(request.provider, request.item_id)
    
    if not details:
        raise HTTPException(status_code=404, detail="Metadata not found")
    
    # Map provider result fields to DVDEntry columns
    if details.get("title"):
        dvd.title = details["title"]
    if "original_title" in details:
        dvd.original_title = details["original_title"]
    if details.get("plot"):
        dvd.plot = details["plot"]
    if "poster_url" in details:
        dvd.poster_url = details["poster_url"]
    if "backdrop_url" in details:
        dvd.backdrop_url = details["backdrop_url"]
    if "director" in details:
        dvd.director = details["director"]
    if "runtime" in details:
        dvd.runtime = details["runtime"]
    if "imdb_id" in details:
        dvd.imdb_id = details["imdb_id"]
    
    # Year may be a string from some providers
    year = details.get("year")
    if year is not None:
        try:
            dvd.year = int(year)
        except (ValueError, TypeError):
            pass
    
    # Genre / cast lists
    genres = details.get("genres")
    if isinstance(genres, list):
        dvd.genre = ", ".join(genres)
    elif "genre" in details:
        dvd.genre = details["genre"]
    
    cast = details.get("cast")
    if isinstance(cast, list):
        dvd.cast = ", ".join(cast)
    elif "cast" in details:
        dvd.cast = cast
    
    # Provider-specific IDs
    if request.provider == "tmdb":
        try:
            dvd.tmdb_id = int(details.get("id"))
        except (ValueError, TypeError):
            dvd.tmdb_id = None
    elif request.provider == "omdb":
        dvd.imdb_id = details.get("id")
    
    dvd.updated_at = datetime.utcnow()
    session.add(dvd)
    session.commit()
    session.refresh(dvd)
    
    return _dvd_entry_to_dict(dvd)


@app.get("/api/jobs")
async def get_jobs(
    status: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Get rip jobs."""
    statement = select(RipJob).order_by(RipJob.started_at.desc())
    
    if status and status.lower() != 'all':
        statement = statement.where(RipJob.status == status)
    elif not status:
        # Default: show active jobs
        statement = statement.where(
            RipJob.status.not_in(["completed", "error", "cancelled"])
        )
    # If status='all', don't filter - show all jobs
    
    jobs = session.exec(statement.limit(50)).all()
    
    return [
        {
            "id": j.id,
            "status": j.status,
            "progress_percent": j.progress_percent,
            "current_step": j.current_step,
            "source_disc_title": j.source_disc_title,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "error_message": j.error_message
        }
        for j in jobs
    ]


@app.get("/api/jobs/{job_id}")
async def get_job_details(
    job_id: int,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Get job details."""
    job = get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Get Celery task status
    celery_status = None
    if job.celery_task_id:
        result = AsyncResult(job.celery_task_id)
        celery_status = {
            "state": result.state,
            "info": result.info
        }
    
    return {
        "id": job.id,
        "status": job.status,
        "progress_percent": job.progress_percent,
        "current_step": job.current_step,
        "step_details": job.step_details,
        "source_disc_title": job.source_disc_title,
        "device_path": job.device_path,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if j.completed_at else None,
        "error_message": job.error_message,
        "celery_status": celery_status
    }


@app.post("/api/jobs")
async def create_job(
    device: str = "/dev/sr0",
    manual_metadata: Optional[dict] = None,
    current_user: str = Depends(require_auth)
):
    """Manually start a rip job."""
    task = process_dvd_task.delay(
        device_path=device,
        manual_metadata=manual_metadata
    )
    
    return {
        "job_id": task.id,
        "status": "queued",
        "message": "Job started successfully"
    }


@app.delete("/api/jobs/{job_id}")
async def cancel_job(
    job_id: int,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Cancel a rip job."""
    job = get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status in ["completed", "error", "cancelled"]:
        raise HTTPException(status_code=400, detail="Job already finished")
    
    # Use job manager to cancel and terminate processes
    job_manager.cancel_job(job_id)
    
    # Revoke Celery task
    if job.celery_task_id:
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    
    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    job.error_message = "Cancelled by user"
    session.add(job)
    session.commit()
    
    return {"status": "cancelled", "message": "Job cancelled successfully"}


@app.delete("/api/jobs/{job_id}/delete")
async def delete_job(
    job_id: int,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Permanently delete a job from the database."""
    job = get_job_by_id(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Only allow deletion of finished jobs
    if job.status not in ["completed", "error", "cancelled"]:
        raise HTTPException(status_code=400, detail="Cannot delete active job. Cancel it first.")
    
    session.delete(job)
    session.commit()
    
    return {"status": "deleted", "message": f"Job {job_id} deleted successfully"}


# Configuration routes

@app.get("/api/config")
async def get_config(current_user: str = Depends(require_auth)):
    """Get current configuration."""
    settings = get_settings()
    
    return {
        "formats": {
            "video_codec": settings.formats.video_codec,
            "audio_codec": settings.formats.audio_codec,
            "container": settings.formats.container,
            "crf": settings.formats.crf,
            "preset": settings.formats.preset
        },
        "destination": {
            "type": settings.destination.type,
            "local": {
                "path": settings.destination.local.path
            },
            "ssh": {
                "host": settings.destination.ssh.host,
                "user": settings.destination.ssh.user,
                "remote_path": settings.destination.ssh.remote_path
            }
        },
        "metadata": {
            "providers": settings.metadata.providers,
            "api_keys": {
                "tmdb": "***" if settings.metadata.api_keys.get("tmdb") else "",
                "omdb": "***" if settings.metadata.api_keys.get("omdb") else ""
            }
        },
        "dvd_device": settings.dvd_device
    }


@app.post("/api/config")
async def update_config(
    config: dict,
    current_user: str = Depends(require_auth)
):
    """Update configuration."""
    new_settings = update_settings(config)
    return {"status": "saved"}


# SSH Key routes

@app.get("/api/ssh-key/status")
async def get_ssh_key_status(current_user: str = Depends(require_auth)):
    """Check if SSH key is uploaded and get its fingerprint."""
    ssh_key_path = Path("/app/config/ssh_key")
    
    if not ssh_key_path.exists():
        return {"uploaded": False}
    
    # Get key fingerprint
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(ssh_key_path)],
            capture_output=True,
            text=True,
            check=True
        )
        # Parse fingerprint from output
        parts = result.stdout.strip().split()
        if len(parts) >= 2:
            return {
                "uploaded": True,
                "fingerprint": parts[1],
                "type": parts[0] if len(parts) > 2 else "unknown"
            }
    except:
        pass
    
    return {"uploaded": True, "fingerprint": "unknown"}


@app.post("/api/ssh-key/upload")
async def upload_ssh_key(
    file: UploadFile = File(...),
    current_user: str = Depends(require_auth)
):
    """Upload an SSH private key."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Read file content
    content = await file.read()
    
    # Basic validation - check it looks like a private key
    content_str = content.decode('utf-8', errors='ignore')
    if 'PRIVATE KEY' not in content_str and 'openssh' not in content_str.lower():
        raise HTTPException(status_code=400, detail="File does not appear to be a valid SSH private key")
    
    # Save key to config directory
    ssh_key_path = Path("/app/config/ssh_key")
    
    try:
        with open(ssh_key_path, 'wb') as f:
            f.write(content)
        
        # Set secure permissions (owner read/write only)
        os.chmod(ssh_key_path, 0o600)
        
        # Update config to use this key
        settings = get_settings()
        if settings.destination.type == "ssh":
            config_update = {
                "destination": {
                    "type": "ssh",
                    "ssh": {
                        "key_path": str(ssh_key_path)
                    }
                }
            }
            update_settings(config_update)
        
        return {
            "status": "uploaded",
            "message": "SSH key uploaded successfully. Make sure to configure the SSH destination settings."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save SSH key: {str(e)}")


@app.delete("/api/ssh-key")
async def delete_ssh_key(current_user: str = Depends(require_auth)):
    """Delete the uploaded SSH key."""
    ssh_key_path = Path("/app/config/ssh_key")
    
    if ssh_key_path.exists():
        ssh_key_path.unlink()
    
    # Clear key_path from config
    settings = get_settings()
    if settings.destination.type == "ssh":
        config_update = {
            "destination": {
                "type": "ssh",
                "ssh": {
                    "key_path": ""
                }
            }
        }
        update_settings(config_update)
    
    return {"status": "deleted"}


# Metadata routes

@app.get("/api/metadata/search")
async def search_metadata(
    q: str,
    year: Optional[int] = None,
    current_user: str = Depends(require_auth)
):
    """Search for movie metadata."""
    settings = get_settings()
    fetcher = MetadataFetcher(settings)
    
    results = await fetcher.search(q, year)
    return {"results": results}


@app.get("/api/metadata/{provider}/{item_id}")
async def get_metadata_details(
    provider: str,
    item_id: str,
    current_user: str = Depends(require_auth)
):
    """Get detailed metadata."""
    settings = get_settings()
    fetcher = MetadataFetcher(settings)
    
    details = await fetcher.get_details(provider, item_id)
    if not details:
        raise HTTPException(status_code=404, detail="Not found")
    
    return details


# Drive status

@app.get("/api/drive/status")
async def get_drive_status(current_user: str = Depends(require_auth)):
    """Get DVD drive status."""
    settings = get_settings()
    
    try:
        ripper = DVDRipper(settings)
        
        # Check if disc is present
        is_present = ripper._is_disc_present()
        
        if is_present:
            disc_info = ripper.get_disc_info(settings.dvd_device)
            return {
                "status": "loaded",
                "has_disc": True,
                "disc_info": disc_info
            }
        else:
            return {
                "status": "empty",
                "has_disc": False
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@app.post("/api/drive/eject")
async def eject_drive(current_user: str = Depends(require_auth)):
    """Eject DVD drive."""
    import os
    settings = get_settings()
    
    # Check if device exists
    if not os.path.exists(settings.dvd_device):
        raise HTTPException(
            status_code=404, 
            detail=f"DVD device {settings.dvd_device} not found"
        )
    
    ripper = DVDRipper(settings)
    
    if ripper.eject_disc(settings.dvd_device):
        return {"status": "ejected"}
    else:
        raise HTTPException(
            status_code=500, 
            detail="Failed to eject drive. Check that the container has proper device permissions (privileged mode, cap_add: SYS_ADMIN)."
        )


# Statistics

@app.get("/api/stats")
async def get_stats(
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Get system statistics."""
    settings = get_settings()
    
    # Count DVDs
    total_dvds = session.exec(select(DVDEntry)).all()
    total_size = sum(d.file_size for d in total_dvds)
    
    # Count jobs
    from sqlalchemy import func
    jobs_stats = session.exec(
        select(RipJob.status, func.count(RipJob.id)).group_by(RipJob.status)
    ).all()
    
    return {
        "library": {
            "total_dvds": len(total_dvds),
            "total_size_bytes": total_size,
            "total_size_gb": round(total_size / (1024**3), 2)
        },
        "jobs": {status: count for status, count in jobs_stats},
        "storage": {
            "destination": settings.destination.type,
            "path": settings.destination.local.path if settings.destination.type == "local" else settings.destination.ssh.remote_path
        }
    }


# Log Viewer Routes

@app.get("/api/logs")
async def get_logs(
    current_user: str = Depends(require_auth)
):
    """Get list of available log files."""
    logs = log_viewer.get_available_logs()
    return {"logs": logs}


@app.get("/api/logs/{log_name}")
async def get_log_content(
    log_name: str,
    lines: int = 100,
    search: Optional[str] = None,
    current_user: str = Depends(require_auth)
):
    """Get content of a specific log file."""
    result = log_viewer.get_log_content(log_name, lines, search)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/logs/service/{service_name}")
async def get_service_logs(
    service_name: str,
    current_user: str = Depends(require_auth)
):
    """Get logs for a specific service."""
    logs = log_viewer.get_logs_by_service(service_name)
    return {"service": service_name, "logs": logs}


# Duplicate Check Route

@app.post("/api/check-duplicate")
async def check_duplicate(
    disc_label: Optional[str] = None,
    disc_size: int = 0,
    current_user: str = Depends(require_auth)
):
    """Check if a DVD is already in the library."""
    result = duplicate_checker.check_disc_in_library(disc_label, disc_size)
    
    # Convert DVDEntry objects to dict for JSON response
    entries = []
    for entry in result["matching_entries"]:
        entries.append({
            "id": entry.id,
            "title": entry.title,
            "year": entry.year,
            "file_path": entry.file_path,
            "created_at": entry.created_at.isoformat() if entry.created_at else None
        })
    
    return {
        "is_duplicate": result["is_duplicate"],
        "message": result["message"],
        "matching_entries": entries
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
