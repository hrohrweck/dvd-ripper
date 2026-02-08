"""Celery background tasks for DVD processing."""
import os
import shutil
import json
import tempfile
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from celery import Celery, states
from celery.exceptions import Ignore

from app.config import get_settings
from app.database import (
    create_rip_job, update_job_status, create_dvd_entry, 
    get_session_context, RipJob, DVDEntry
)
from sqlmodel import select
from app.ripper import DVDRipper
from app.metadata.fetcher import MetadataFetcher

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Celery
settings = get_settings()
celery_app = Celery(
    'dvd_ripper',
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=['app.tasks']
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600 * 4,  # 4 hours max
    worker_prefetch_multiplier=1,
)


def _save_to_archive_ssh(
    source_file: Path, 
    metadata: dict, 
    settings, 
    safe_title: str, 
    folder_name: str
) -> str:
    """Transfer file to remote SSH destination using SFTP."""
    import paramiko
    
    ssh_config = settings.destination.ssh
    host = ssh_config.host
    user = ssh_config.user
    key_path = ssh_config.key_path
    remote_base_path = ssh_config.remote_path
    
    if not host or not user:
        raise ValueError("SSH host and user must be configured")
    
    if not remote_base_path:
        remote_base_path = "/archive"
    
    # Build remote paths
    remote_dir = f"{remote_base_path.rstrip('/')}/{folder_name}"
    ext = settings.formats.container
    remote_file_name = f"{safe_title}.{ext}"
    remote_file_path = f"{remote_dir}/{remote_file_name}"
    
    # Handle duplicate names
    counter = 1
    original_remote_file_path = remote_file_path
    while True:
        # Check if file exists (we'll handle this after connection)
        break  # We'll check and handle duplicates during transfer
    
    # Establish SSH connection
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # Connect using key or password
        connect_kwargs = {
            "hostname": host,
            "username": user,
            "timeout": 30,
        }
        
        if key_path and Path(key_path).exists():
            connect_kwargs["key_filename"] = key_path
        elif key_path:
            # Try to use the key path as a string (might be in container)
            connect_kwargs["key_filename"] = key_path
        else:
            # Try default keys
            default_keys = [
                "/root/.ssh/id_rsa",
                "/root/.ssh/id_ed25519",
                "/app/config/ssh_key",
                os.path.expanduser("~/.ssh/id_rsa"),
                os.path.expanduser("~/.ssh/id_ed25519"),
            ]
            for key_file in default_keys:
                if Path(key_file).exists():
                    connect_kwargs["key_filename"] = key_file
                    break
        
        ssh.connect(**connect_kwargs)
        
        # Open SFTP session
        sftp = ssh.open_sftp()
        
        try:
            # Create destination directory
            try:
                sftp.mkdir(remote_dir)
            except IOError:
                # Directory may already exist
                pass
            
            # Check for duplicate files and find unique name
            counter = 1
            remote_file_path = original_remote_file_path
            remote_file_name_final = f"{safe_title}.{ext}"
            
            while True:
                try:
                    sftp.stat(remote_file_path)
                    # File exists, try next name
                    remote_file_name_final = f"{safe_title}_{counter}.{ext}"
                    remote_file_path = f"{remote_dir}/{remote_file_name_final}"
                    counter += 1
                except IOError:
                    # File doesn't exist, we can use this name
                    break
            
            # Transfer video file with progress callback
            logger.info(f"Transferring {source_file} to {host}:{remote_file_path}")
            
            file_size = source_file.stat().st_size
            uploaded_bytes = 0
            last_percent = 0
            
            def progress_callback(bytes_transferred, total_bytes):
                nonlocal uploaded_bytes, last_percent
                uploaded_bytes = bytes_transferred
                percent = int((bytes_transferred / total_bytes) * 100)
                if percent >= last_percent + 10:  # Log every 10%
                    logger.info(f"SSH transfer progress: {percent}%")
                    last_percent = percent
            
            sftp.put(str(source_file), remote_file_path, callback=progress_callback)
            logger.info(f"Transfer complete: {remote_file_path}")
            
            # Transfer metadata JSON
            metadata_json = json.dumps(metadata, indent=2)
            metadata_remote_path = f"{remote_dir}/metadata.json"
            
            # Write metadata to a temporary file and transfer
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
                tmp.write(metadata_json)
                tmp_path = tmp.name
            
            try:
                sftp.put(tmp_path, metadata_remote_path)
            finally:
                os.unlink(tmp_path)
            
            return remote_file_path
            
        finally:
            sftp.close()
            
    except paramiko.AuthenticationException as e:
        logger.error(f"SSH authentication failed: {e}")
        raise RuntimeError(f"SSH authentication failed for {user}@{host}: {e}")
    except paramiko.SSHException as e:
        logger.error(f"SSH connection error: {e}")
        raise RuntimeError(f"SSH connection error to {host}: {e}")
    except Exception as e:
        logger.error(f"SSH transfer failed: {e}")
        raise RuntimeError(f"Failed to transfer file via SSH: {e}")
    finally:
        ssh.close()


def update_progress(task, job_id: int, step: str, percent: int, details: str = ""):
    """Update job progress in database and Celery state."""
    try:
        with get_session_context() as session:
            update_job_status(
                session, 
                job_id,
                status=step.lower().replace(" ", "_"),
                progress_percent=percent,
                current_step=step,
                step_details=details
            )
            
        task.update_state(
            state='PROGRESS',
            meta={
                'step': step,
                'percent': percent,
                'details': details
            }
        )
    except Exception as e:
        logger.error(f"Failed to update progress: {e}")


def save_to_archive(source_file: Path, metadata: dict, settings) -> Path | str:
    """Move file to archive location."""
    dest_config = settings.destination
    
    # Create destination folder
    title = metadata.get('title', 'Unknown')
    year = metadata.get('year', '')
    
    # Sanitize folder name
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    folder_name = f"{safe_title} ({year})" if year else safe_title
    
    if dest_config.type == "local":
        dest_dir = Path(dest_config.local.path) / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        # Move file
        ext = settings.formats.container
        dest_file = dest_dir / f"{safe_title}.{ext}"
        
        # Handle duplicate names
        counter = 1
        while dest_file.exists():
            dest_file = dest_dir / f"{safe_title}_{counter}.{ext}"
            counter += 1
            
        shutil.move(str(source_file), str(dest_file))
        
        # Save metadata JSON
        with open(dest_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
            
        return dest_file
        
    elif dest_config.type == "ssh":
        return _save_to_archive_ssh(source_file, metadata, settings, safe_title, folder_name)
    else:
        raise ValueError(f"Unknown destination type: {dest_config.type}")


@celery_app.task(bind=True, max_retries=3)
def process_dvd_task(
    self,
    device_path: str,
    disc_label: Optional[str] = None,
    manual_metadata: Optional[dict] = None
):
    """
    Main DVD processing task.
    
    Workflow:
    1. Create job record
    2. Rip DVD
    3. Transcode
    4. Fetch metadata (if not provided)
    5. Archive file
    6. Create library entry
    7. Cleanup
    """
    job_id = None
    temp_output = None
    
    try:
        # Step 1: Create job record
        with get_session_context() as session:
            job = create_rip_job(
                session,
                device_path=device_path,
                source_disc_title=disc_label,
                status="ripping",
                current_step="Initializing..."
            )
            job_id = job.id
            # Store job_id in request context (not kwargs to avoid retry issues)
            self.request.job_id = job_id
            
        # Update Celery task ID
        with get_session_context() as session:
            job = session.get(RipJob, job_id)
            job.celery_task_id = self.request.id
            session.add(job)
            session.commit()
            
        settings = get_settings()
        ripper = DVDRipper(settings)
        
        def progress_callback(step: str, percent: int, details: str):
            update_progress(self, job_id, step, percent, details)
            
        # Step 2: Find main title
        update_progress(self, job_id, "analyzing", 0, "Analyzing disc structure...")
        
        # Wait a moment for the drive to be fully ready
        import time
        time.sleep(3)
        
        main_title = ripper.find_main_title(device_path)
        
        if not main_title:
            logger.error(f"Could not detect main title on {device_path}")
            raise Exception("Could not detect main title on disc")
            
        # Step 3: Rip
        update_progress(self, job_id, "ripping", 0, f"Ripping title {main_title.index}...")
        
        rip_result = ripper.rip_title(
            device_path,
            main_title.index,
            progress_callback
        )
        
        if not rip_result.success:
            raise Exception(f"Ripping failed: {rip_result.error_message}")
            
        ripped_file = rip_result.output_path
        
        # Step 4: Transcode
        update_progress(self, job_id, "transcoding", 0, "Starting transcoding...")
        
        output_name = disc_label or "movie"
        output_path = ripper.temp_dir / f"{output_name}.{settings.formats.container}"
        
        transcode_result = ripper.transcode(
            ripped_file,
            output_path,
            progress_callback
        )
        
        if not transcode_result.success:
            raise Exception(f"Transcoding failed: {transcode_result.error_message}")
            
        temp_output = transcode_result.output_path
        file_size = temp_output.stat().st_size
        
        # Step 5: Metadata
        metadata = manual_metadata or {}
        
        if not metadata.get('title'):
            update_progress(self, job_id, "fetching_metadata", 0, "Fetching movie metadata...")
            
            fetcher = MetadataFetcher(settings)
            import asyncio
            
            # Search by disc label
            search_title = disc_label or "Movie"
            # Remove common suffixes/prefixes
            for suffix in ['DVD', 'DISC', 'BLU-RAY', 'BD']:
                search_title = search_title.replace(suffix, '').strip()
                
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                search_results = loop.run_until_complete(fetcher.search(search_title))
                
                if search_results:
                    # Use first result
                    best_match = search_results[0]
                    details = loop.run_until_complete(
                        fetcher.get_details(best_match['provider'], best_match['id'])
                    )
                    
                    if details:
                        metadata.update(details)
            finally:
                loop.close()
                
        # Use disc label as fallback title
        if not metadata.get('title'):
            metadata['title'] = disc_label or "Unknown Movie"
            
        # Step 6: Archive
        update_progress(self, job_id, "archiving", 50, "Moving to archive...")
        
        final_path = save_to_archive(temp_output, metadata, settings)
        
        update_progress(self, job_id, "archiving", 100, f"Saved to {final_path}")
        
        # Step 7: Create library entry
        with get_session_context() as session:
            dvd = create_dvd_entry(
                session,
                title=metadata.get('title', 'Unknown'),
                original_title=metadata.get('original_title'),
                year=int(metadata['year']) if metadata.get('year') and str(metadata['year']).isdigit() else None,
                plot=metadata.get('plot'),
                poster_url=metadata.get('poster_url'),
                backdrop_url=metadata.get('backdrop_url'),
                genre=', '.join(metadata['genres']) if isinstance(metadata.get('genres'), list) else metadata.get('genre'),
                director=metadata.get('director'),
                cast=', '.join(metadata['cast']) if isinstance(metadata.get('cast'), list) else metadata.get('cast'),
                runtime=metadata.get('runtime'),
                imdb_id=metadata.get('imdb_id'),
                tmdb_id=int(metadata['tmdb_id']) if metadata.get('tmdb_id') and str(metadata['tmdb_id']).isdigit() else None,
                file_path=str(final_path),
                file_size=file_size,
                file_format=settings.formats.container,
                video_codec=settings.formats.video_codec,
                audio_codec=settings.formats.audio_codec,
                status='completed',
                resolution=None  # Could detect this
            )
            
            # Update job with DVD entry reference
            job = session.get(RipJob, job_id)
            job.dvd_entry_id = dvd.id
            session.add(job)
            session.commit()
            
        # Update job as completed
        with get_session_context() as session:
            update_job_status(
                session,
                job_id,
                status='completed',
                progress_percent=100,
                current_step='Complete'
            )
            
        # Step 8: Cleanup
        ripper.cleanup()
        
        # Step 9: Eject disc
        ripper.eject_disc(device_path)
        
        return {
            'status': 'completed',
            'job_id': job_id,
            'file_path': str(final_path),
            'file_size': file_size,
            'metadata': metadata
        }
        
    except Exception as exc:
        logger.exception("DVD processing failed")
        
        # Update job with error
        if job_id:
            try:
                with get_session_context() as session:
                    update_job_status(
                        session,
                        job_id,
                        status='error',
                        error_message=str(exc)
                    )
            except:
                pass
                
        # Cleanup on failure
        try:
            if 'ripper' in dir():
                ripper.cleanup()
        except:
            pass
            
        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying task (attempt {self.request.retries + 1})")
            raise self.retry(exc=exc, countdown=60)
        else:
            raise Ignore()


@celery_app.task
def cleanup_old_jobs(days: int = 30):
    """Cleanup old completed jobs."""
    from datetime import timedelta
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    with get_session_context() as session:
        statement = select(RipJob).where(
            RipJob.status.in_(['completed', 'error', 'cancelled']),
            RipJob.completed_at < cutoff
        )
        old_jobs = session.exec(statement).all()
        
        for job in old_jobs:
            session.delete(job)
            
        session.commit()
        
    return f"Cleaned up {len(old_jobs)} old jobs"


@celery_app.task
def test_task(x: int, y: int):
    """Simple test task."""
    return x + y
