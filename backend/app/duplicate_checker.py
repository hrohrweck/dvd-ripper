"""DVD Duplicate Detection Module."""
import logging
from typing import Optional, List
from sqlmodel import Session, select
from datetime import datetime, timedelta

from app.database import DVDEntry, RipJob, get_session_context

logger = logging.getLogger(__name__)


class DuplicateChecker:
    """Checks if a DVD has already been ripped."""
    
    def __init__(self):
        pass
    
    def check_disc_in_library(
        self, 
        disc_label: Optional[str] = None,
        disc_size: int = 0,
        fuzzy_match: bool = True
    ) -> dict:
        """
        Check if a DVD is already in the library.
        
        Args:
            disc_label: The disc label/volume name
            disc_size: The disc size in bytes
            fuzzy_match: Whether to use fuzzy matching on title
            
        Returns:
            dict with:
                - is_duplicate: bool
                - matching_entries: List[DVDEntry]
                - message: str
        """
        with get_session_context() as session:
            matches = []
            
            # Check 1: Exact match by disc label vs stored title
            if disc_label:
                # Normalize the disc label (remove common suffixes)
                normalized_label = self._normalize_disc_label(disc_label)
                
                # Look for exact matches
                statement = select(DVDEntry).where(
                    DVDEntry.title == normalized_label
                )
                exact_matches = session.exec(statement).all()
                matches.extend(exact_matches)
                
                # Look for case-insensitive matches if fuzzy_match is enabled
                if fuzzy_match and not exact_matches:
                    all_entries = session.exec(select(DVDEntry)).all()
                    for entry in all_entries:
                        if entry.title and normalized_label.lower() in entry.title.lower():
                            matches.append(entry)
                            break
            
            # Check 2: Check recent rip jobs with same disc label
            # Treat queued or in-flight jobs as duplicates too, so a disc that
            # is already waiting to be resumed/processed does not get ripped a
            # second time if it is re-inserted.
            if disc_label and not matches:
                cutoff = datetime.utcnow() - timedelta(days=30)
                active_statuses = [
                    "queued",
                    "analyzing",
                    "ripping",
                    "transcoding",
                    "fetching_metadata",
                    "archiving",
                    "completed",
                ]
                statement = select(RipJob).where(
                    RipJob.source_disc_title == disc_label,
                    RipJob.status.in_(active_statuses),
                    RipJob.started_at > cutoff
                )
                recent_jobs = session.exec(statement).all()
                if recent_jobs:
                    # Get the DVD entries for these jobs
                    for job in recent_jobs:
                        if job.dvd_entry_id:
                            dvd = session.get(DVDEntry, job.dvd_entry_id)
                            if dvd:
                                matches.append(dvd)
            
            # Remove duplicates from matches
            seen_ids = set()
            unique_matches = []
            for entry in matches:
                if entry.id not in seen_ids:
                    seen_ids.add(entry.id)
                    unique_matches.append(entry)
            
            if unique_matches:
                match_info = []
                for entry in unique_matches:
                    match_info.append(f"'{entry.title}' ({entry.year or 'Unknown Year'})")
                
                message = f"DVD already in library: {', '.join(match_info)}"
                logger.info(f"Duplicate detection: {message}")
                
                return {
                    "is_duplicate": True,
                    "matching_entries": unique_matches,
                    "message": message
                }
            
            return {
                "is_duplicate": False,
                "matching_entries": [],
                "message": "DVD not found in library"
            }
    
    def _normalize_disc_label(self, label: str) -> str:
        """Normalize disc label by removing common suffixes/prefixes."""
        if not label:
            return ""
        
        label = label.strip()
        
        # Remove common suffixes
        suffixes = [
            "_DVD", " DVD", "-DVD",
            "_DISC", " DISC", "-DISC",
            "_BLU-RAY", " BLU-RAY", "-BLU-RAY",
            "_BD", " BD", "-BD",
            "_VIDEO", " VIDEO", "-VIDEO",
            "_MOVIE", " MOVIE", "-MOVIE",
        ]
        
        normalized = label
        for suffix in suffixes:
            if normalized.upper().endswith(suffix.upper()):
                normalized = normalized[:-len(suffix)].strip()
        
        return normalized
    
    def get_library_entry_by_disc_label(self, disc_label: str) -> Optional[DVDEntry]:
        """Get a library entry by disc label."""
        normalized = self._normalize_disc_label(disc_label)
        
        with get_session_context() as session:
            # Try exact match first
            statement = select(DVDEntry).where(DVDEntry.title == normalized)
            result = session.exec(statement).first()
            if result:
                return result
            
            # Try case-insensitive match
            all_entries = session.exec(select(DVDEntry)).all()
            for entry in all_entries:
                if entry.title and normalized.lower() == entry.title.lower():
                    return entry
            
            return None
    
    def log_duplicate_detection(self, disc_label: Optional[str], is_duplicate: bool, message: str):
        """Log the duplicate detection result."""
        if is_duplicate:
            logger.warning(f"DUPLICATE DVD DETECTED: {disc_label} - {message}")
        else:
            logger.info(f"NEW DVD DETECTED: {disc_label} - {message}")


# Global instance
duplicate_checker = DuplicateChecker()


def check_disc_duplicate(disc_label: Optional[str] = None, disc_size: int = 0) -> dict:
    """Convenience function to check if a disc is a duplicate."""
    return duplicate_checker.check_disc_in_library(disc_label, disc_size)
