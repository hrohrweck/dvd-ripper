"""Database models and session management."""
from typing import Optional, List, Generator
from datetime import datetime
from contextlib import contextmanager

from sqlmodel import SQLModel, Field, Relationship, Session, create_engine, select
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class DVDEntry(SQLModel, table=True):
    """Represents a ripped DVD in the library."""
    __tablename__ = "dvd_entries"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    original_title: Optional[str] = None
    year: Optional[int] = None
    plot: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    genre: Optional[str] = None
    director: Optional[str] = None
    cast: Optional[str] = None  # JSON string of cast members
    runtime: Optional[int] = None  # in minutes
    imdb_id: Optional[str] = None
    tmdb_id: Optional[int] = None
    
    file_path: str
    file_size: int
    file_format: str = "mp4"
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    status: str = "processing"  # 'processing', 'completed', 'error'
    error_message: Optional[str] = None
    
    # Relationship
    rip_jobs: List["RipJob"] = Relationship(back_populates="dvd_entry")


class RipJob(SQLModel, table=True):
    """Tracks the status of a ripping job."""
    __tablename__ = "rip_jobs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    dvd_entry_id: Optional[int] = Field(default=None, foreign_key="dvd_entries.id")
    celery_task_id: Optional[str] = None
    
    status: str = "queued"  # 'queued', 'ripping', 'transcoding', 'fetching_metadata', 'archiving', 'completed', 'error', 'cancelled'
    progress_percent: int = Field(default=0, ge=0, le=100)
    current_step: str = ""
    step_details: Optional[str] = None  # Additional info about current step
    
    device_path: str = "/dev/sr0"
    source_disc_title: Optional[str] = None
    
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # Relationship
    dvd_entry: Optional[DVDEntry] = Relationship(back_populates="rip_jobs")


class User(SQLModel, table=True):
    """Admin user for authentication."""
    __tablename__ = "users"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None


class ConfigEntry(SQLModel, table=True):
    """Key-value store for configuration."""
    __tablename__ = "config"
    
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)


def get_engine():
    """Create database engine with appropriate configuration."""
    settings = get_settings()
    
    # Handle SQLite specially for async support
    if settings.database.url.startswith("sqlite"):
        return create_engine(
            settings.database.url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=settings.environment == "development"
        )
    else:
        return create_engine(
            settings.database.url,
            echo=settings.environment == "development"
        )


engine = get_engine()


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Get database session for dependency injection."""
    with Session(engine) as session:
        yield session


@contextmanager
def get_session_context() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    with Session(engine) as session:
        yield session


# Database operations


def get_dvd_by_id(session: Session, dvd_id: int) -> Optional[DVDEntry]:
    """Get DVD entry by ID."""
    return session.get(DVDEntry, dvd_id)


def get_dvd_by_title(session: Session, title: str) -> Optional[DVDEntry]:
    """Get DVD entry by title."""
    statement = select(DVDEntry).where(DVDEntry.title == title)
    return session.exec(statement).first()


def get_all_dvds(session: Session, skip: int = 0, limit: int = 100) -> List[DVDEntry]:
    """Get all DVD entries with pagination."""
    statement = select(DVDEntry).order_by(DVDEntry.created_at.desc()).offset(skip).limit(limit)
    return session.exec(statement).all()


def get_active_jobs(session: Session) -> List[RipJob]:
    """Get all active (non-completed) rip jobs."""
    statement = select(RipJob).where(
        RipJob.status.not_in(["completed", "error", "cancelled"])
    ).order_by(RipJob.started_at.desc())
    return session.exec(statement).all()


def get_job_by_id(session: Session, job_id: int) -> Optional[RipJob]:
    """Get rip job by ID."""
    return session.get(RipJob, job_id)


def get_job_by_celery_id(session: Session, celery_id: str) -> Optional[RipJob]:
    """Get rip job by Celery task ID."""
    statement = select(RipJob).where(RipJob.celery_task_id == celery_id)
    return session.exec(statement).first()


def create_dvd_entry(session: Session, **kwargs) -> DVDEntry:
    """Create a new DVD entry."""
    dvd = DVDEntry(**kwargs)
    session.add(dvd)
    session.commit()
    session.refresh(dvd)
    return dvd


def create_rip_job(session: Session, **kwargs) -> RipJob:
    """Create a new rip job."""
    job = RipJob(**kwargs)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def update_job_status(session: Session, job_id: int, status: str, **kwargs) -> Optional[RipJob]:
    """Update rip job status."""
    job = session.get(RipJob, job_id)
    if job:
        job.status = status
        for key, value in kwargs.items():
            setattr(job, key, value)
        if status in ["completed", "error", "cancelled"]:
            job.completed_at = datetime.utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
    return job
