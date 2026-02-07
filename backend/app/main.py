"""FastAPI application main entry point."""
import os
import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
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
        if disc_info.is_dvd_video:
            # Auto-trigger rip if configured (or queue for manual approval)
            process_dvd_task.delay(
                device_path=disc_info.device,
                disc_label=disc_info.label
            )
    
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
        "file_path": dvd.file_path,
        "file_size": dvd.file_size,
        "file_format": dvd.file_format,
        "resolution": dvd.resolution,
        "status": dvd.status,
        "created_at": dvd.created_at.isoformat() if dvd.created_at else None
    }


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
    
    # Delete file if requested
    if delete_file and dvd.file_path:
        try:
            import os
            os.remove(dvd.file_path)
        except Exception as e:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to delete file: {e}"
            )
    
    session.delete(dvd)
    session.commit()
    
    return {"status": "deleted"}


# Job routes

@app.get("/api/jobs")
async def get_jobs(
    status: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Get rip jobs."""
    statement = select(RipJob).order_by(RipJob.started_at.desc())
    
    if status:
        statement = statement.where(RipJob.status == status)
    else:
        # Default: show active jobs
        statement = statement.where(
            RipJob.status.not_in(["completed", "error", "cancelled"])
        )
    
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
    
    # Revoke Celery task
    if job.celery_task_id:
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    
    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    session.add(job)
    session.commit()
    
    return {"status": "cancelled"}


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
    settings = get_settings()
    ripper = DVDRipper(settings)
    
    if ripper.eject_disc(settings.dvd_device):
        return {"status": "ejected"}
    else:
        raise HTTPException(status_code=500, detail="Failed to eject drive")


# Statistics

@app.get("/api/stats")
async def get_stats(
    session: Session = Depends(get_session),
    current_user: str = Depends(require_auth)
):
    """Get system statistics."""
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
