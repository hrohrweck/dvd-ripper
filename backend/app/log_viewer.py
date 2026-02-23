"""Log Viewer Module for viewing application logs."""
import os
import glob
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class LogViewer:
    """View and manage application logs."""
    
    # Default log paths to search
    DEFAULT_LOG_PATHS = [
        "/var/log/supervisor/*.log",
        "/var/log/nginx/*.log",
        "/app/data/*.log",
        "/tmp/*.log",
        "/root/MakeMKV_log.txt",
    ]
    
    def __init__(self):
        self.log_paths = self.DEFAULT_LOG_PATHS.copy()
    
    def get_available_logs(self) -> List[Dict]:
        """Get list of available log files."""
        logs = []
        seen_files = set()
        
        for pattern in self.log_paths:
            for log_file in glob.glob(pattern):
                if log_file in seen_files:
                    continue
                seen_files.add(log_file)
                
                try:
                    stat = os.stat(log_file)
                    logs.append({
                        "name": Path(log_file).name,
                        "path": log_file,
                        "size": stat.st_size,
                        "size_human": self._format_size(stat.st_size),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "description": self._get_log_description(log_file)
                    })
                except Exception as e:
                    logger.warning(f"Could not stat log file {log_file}: {e}")
        
        # Sort by modification time (newest first)
        logs.sort(key=lambda x: x["modified"], reverse=True)
        return logs
    
    def get_log_content(
        self, 
        log_name: str, 
        lines: int = 100,
        search: Optional[str] = None
    ) -> Dict:
        """
        Get content of a specific log file.
        
        Args:
            log_name: Name of the log file (or full path)
            lines: Number of lines to return from the end (default 100)
            search: Optional search term to filter lines
            
        Returns:
            dict with log content and metadata
        """
        # Find the log file
        log_path = self._find_log_file(log_name)
        if not log_path:
            return {
                "error": f"Log file '{log_name}' not found",
                "content": "",
                "lines_returned": 0,
                "total_lines": 0
            }
        
        try:
            # Read the file
            with open(log_path, 'r', errors='replace') as f:
                content = f.read()
            
            all_lines = content.splitlines()
            total_lines = len(all_lines)
            
            # Filter by search term if provided
            if search:
                filtered_lines = [line for line in all_lines if search.lower() in line.lower()]
            else:
                filtered_lines = all_lines
            
            # Get last N lines
            if lines > 0 and len(filtered_lines) > lines:
                returned_lines = filtered_lines[-lines:]
            else:
                returned_lines = filtered_lines
            
            return {
                "name": Path(log_path).name,
                "path": log_path,
                "content": "\n".join(returned_lines),
                "lines_returned": len(returned_lines),
                "total_lines": total_lines,
                "filtered_lines": len(filtered_lines) if search else None,
                "search_term": search
            }
            
        except Exception as e:
            logger.error(f"Error reading log file {log_path}: {e}")
            return {
                "error": f"Could not read log file: {str(e)}",
                "content": "",
                "lines_returned": 0,
                "total_lines": 0
            }
    
    def get_logs_by_service(self, service: str) -> List[Dict]:
        """Get logs for a specific service."""
        all_logs = self.get_available_logs()
        
        service_patterns = {
            "celery": ["celery"],
            "fastapi": ["fastapi", "uvicorn"],
            "nginx": ["nginx"],
            "supervisor": ["supervisor"],
            "makemkv": ["makemkv", "MakeMKV"],
            "dvd": ["dvd", "ripper"],
        }
        
        patterns = service_patterns.get(service.lower(), [service.lower()])
        
        matching = []
        for log in all_logs:
            log_name_lower = log["name"].lower()
            if any(pattern in log_name_lower for pattern in patterns):
                matching.append(log)
        
        return matching
    
    def _find_log_file(self, log_name: str) -> Optional[str]:
        """Find a log file by name or path."""
        # If it's a full path that exists, use it
        if os.path.isfile(log_name):
            return log_name
        
        # Search in default paths
        for pattern in self.log_paths:
            for log_file in glob.glob(pattern):
                if Path(log_file).name == log_name:
                    return log_file
        
        return None
    
    def _format_size(self, size_bytes: int) -> str:
        """Format byte size to human readable."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
    
    def _get_log_description(self, log_path: str) -> str:
        """Get a description for a log file based on its name."""
        name = Path(log_path).name.lower()
        
        descriptions = {
            "celery-worker": "Celery worker processing logs",
            "celery-beat": "Celery scheduled task logs",
            "fastapi": "Web API request logs",
            "nginx": "Web server access/error logs",
            "supervisor": "Process manager logs",
            "makemkv": "DVD ripping tool logs",
            "mkmkv": "MakeMKV debug logs",
            "dvd": "DVD processing logs",
        }
        
        for key, desc in descriptions.items():
            if key in name:
                return desc
        
        return "Application log"


# Global instance
log_viewer = LogViewer()


def get_logs() -> List[Dict]:
    """Convenience function to get all available logs."""
    return log_viewer.get_available_logs()


def get_log(log_name: str, lines: int = 100, search: Optional[str] = None) -> Dict:
    """Convenience function to get a specific log."""
    return log_viewer.get_log_content(log_name, lines, search)
