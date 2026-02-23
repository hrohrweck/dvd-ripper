"""Job Manager for tracking and controlling active jobs."""
import os
import signal
import logging
from typing import Dict, Optional, Set
from pathlib import Path

logger = logging.getLogger(__name__)


class JobManager:
    """Manages active ripping jobs and their subprocesses."""
    
    def __init__(self):
        self._active_jobs: Dict[int, dict] = {}
        self._cancelled_jobs: Set[int] = set()
        self._processes: Dict[int, list] = {}
    
    def register_job(self, job_id: int, process=None):
        """Register a new active job."""
        self._active_jobs[job_id] = {
            'processes': [],
            'cancelled': False
        }
        if process:
            self._active_jobs[job_id]['processes'].append(process)
        logger.info(f"Registered job {job_id}")
    
    def register_process(self, job_id: int, process):
        """Register a subprocess for a job."""
        if job_id in self._active_jobs:
            self._active_jobs[job_id]['processes'].append(process)
            logger.debug(f"Registered process {process.pid} for job {job_id}")
    
    def is_job_cancelled(self, job_id: int) -> bool:
        """Check if a job has been cancelled."""
        if job_id in self._active_jobs:
            return self._active_jobs[job_id]['cancelled']
        return job_id in self._cancelled_jobs
    
    def cancel_job(self, job_id: int) -> bool:
        """Cancel a job and terminate its processes."""
        logger.info(f"Cancelling job {job_id}")
        
        self._cancelled_jobs.add(job_id)
        
        if job_id not in self._active_jobs:
            logger.info(f"Job {job_id} not currently active, marked for cancellation")
            return True
        
        self._active_jobs[job_id]['cancelled'] = True
        
        # Terminate all processes
        terminated = []
        for process in self._active_jobs[job_id]['processes']:
            try:
                if process and process.poll() is None:  # Process is still running
                    logger.info(f"Terminating process {process.pid} for job {job_id}")
                    process.terminate()
                    terminated.append(process)
            except Exception as e:
                logger.error(f"Error terminating process: {e}")
        
        # Wait for processes to terminate, then kill if necessary
        import time
        time.sleep(1)
        
        for process in terminated:
            try:
                if process.poll() is None:  # Still running
                    logger.warning(f"Killing process {process.pid}")
                    process.kill()
            except Exception as e:
                logger.error(f"Error killing process: {e}")
        
        return True
    
    def unregister_job(self, job_id: int):
        """Unregister a completed job."""
        if job_id in self._active_jobs:
            del self._active_jobs[job_id]
        logger.info(f"Unregistered job {job_id}")
    
    def get_active_jobs(self) -> list:
        """Get list of active job IDs."""
        return list(self._active_jobs.keys())


# Global job manager instance
job_manager = JobManager()


def check_job_cancellation(job_id: int) -> bool:
    """Check if a job should be cancelled (for use in long-running operations)."""
    return job_manager.is_job_cancelled(job_id)
