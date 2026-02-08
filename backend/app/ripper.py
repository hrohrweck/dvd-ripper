"""DVD Ripping and Transcoding Pipeline."""
import os
import subprocess
import tempfile
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import shutil

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class TitleInfo:
    """Information about a DVD title."""
    index: int
    duration_seconds: int
    size_bytes: int
    chapters: int
    audio_tracks: List[Dict]
    subtitle_tracks: List[Dict]


@dataclass
class RipResult:
    """Result of ripping operation."""
    success: bool
    output_path: Optional[Path] = None
    error_message: Optional[str] = None
    title_info: Optional[TitleInfo] = None


class DVDRipper:
    """Handles DVD ripping and transcoding."""
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.temp_dir: Optional[Path] = None
        
    def _create_temp_dir(self) -> Path:
        """Create temporary directory for processing."""
        # Use tmpfs for faster I/O if available
        temp_base = "/dev/shm" if Path("/dev/shm").exists() else None
        self.temp_dir = Path(tempfile.mkdtemp(prefix="dvdrip_", dir=temp_base))
        return self.temp_dir
        
    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")
                
    def get_disc_info(self, device: str) -> Dict:
        """Get information about the disc using makemkvcon."""
        try:
            # Check if makemkvcon is available
            result = subprocess.run(["which", "makemkvcon"], capture_output=True)
            if result.returncode != 0:
                logger.error("makemkvcon not found in PATH")
                return {}
            
            logger.info(f"Running makemkvcon to get disc info from {device}")
            cmd = ["makemkvcon", "-r", "info", f"dev:{device}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for very slow drives
            )
            
            if result.returncode != 0:
                logger.error(f"makemkvcon info failed with code {result.returncode}")
                logger.error(f"stderr: {result.stderr}")
                logger.error(f"stdout: {result.stdout}")
                return {}
            
            parsed = self._parse_makemkv_info(result.stdout)
            logger.info(f"Found {len(parsed.get('titles', []))} titles on disc")
            return parsed
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout getting disc info (300s exceeded) - drive may be slow or disc damaged")
            return {}
        except Exception as e:
            logger.error(f"Error getting disc info: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
            
    def _parse_makemkv_info(self, output: str) -> Dict:
        """Parse makemkvcon info output."""
        info = {"titles": []}
        current_title = None
        
        for line in output.splitlines():
            line = line.strip()
            
            if line.startswith("CINFO:2,0,"):
                # Disc name
                info["disc_name"] = line.split(",")[-1].strip('"')
            elif line.startswith("TINFO:"):
                parts = line.split(",")
                title_idx = int(parts[0].split(":")[1])
                
                if current_title is None or current_title["index"] != title_idx:
                    current_title = {"index": title_idx, "audio": [], "subtitles": []}
                    info["titles"].append(current_title)
                    
                attr_id = parts[1]
                value = parts[2].strip('"') if len(parts) > 2 else ""
                
                if attr_id == "2":  # Title name
                    current_title["name"] = value
                elif attr_id == "9":  # Duration
                    current_title["duration"] = value
                elif attr_id == "10":  # Size
                    current_title["size"] = value
                elif attr_id == "11":  # Chapters
                    current_title["chapters"] = value
                    
        return info
        
    def find_main_title(self, device: str) -> Optional[TitleInfo]:
        """Find the main feature title (usually the longest)."""
        disc_info = self.get_disc_info(device)
        
        if not disc_info or "titles" not in disc_info:
            return None
            
        titles = disc_info["titles"]
        if not titles:
            return None
            
        # Find longest title
        main_title = max(titles, key=lambda t: self._parse_size(t.get("size", "0")))
        
        return TitleInfo(
            index=main_title["index"],
            duration_seconds=self._parse_duration(main_title.get("duration", "0:00:00")),
            size_bytes=self._parse_size(main_title.get("size", "0")),
            chapters=int(main_title.get("chapters", 0)),
            audio_tracks=[],
            subtitle_tracks=[]
        )
        
    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string to seconds."""
        try:
            parts = duration_str.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except:
            pass
        return 0
        
    def _parse_size(self, size_str: str) -> int:
        """Parse size string to bytes."""
        try:
            # Remove any non-numeric characters except decimal point
            import re
            match = re.match(r"([\d.]+)\s*(\w*)", size_str)
            if match:
                value = float(match.group(1))
                unit = match.group(2).upper()
                
                multipliers = {
                    "B": 1,
                    "KB": 1024,
                    "MB": 1024**2,
                    "GB": 1024**3,
                    "TB": 1024**4,
                }
                
                return int(value * multipliers.get(unit, 1))
        except:
            pass
        return 0
        
    def rip_title(
        self,
        device: str,
        title_index: int = 0,
        progress_callback: Optional[callable] = None
    ) -> RipResult:
        """Rip a specific title from the DVD."""
        temp_dir = self._create_temp_dir()
        output_dir = temp_dir / "rip"
        output_dir.mkdir()
        
        try:
            # Use makemkvcon to rip the title
            # title_index 0 means auto-select main title
            cmd = [
                "makemkvcon",
                "--minlength=600",  # Skip titles shorter than 10 minutes
                "--noscan",  # Don't rescan
                "mkv",
                f"dev:{device}",
                str(title_index),
                str(output_dir)
            ]
            
            logger.info(f"Ripping title {title_index} from {device}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor progress
            for line in process.stdout:
                line = line.strip()
                logger.debug(f"makemkvcon: {line}")
                
                # Parse progress
                if "Progress" in line and progress_callback:
                    try:
                        percent = int(line.split("%")[0].split()[-1])
                        progress_callback("ripping", percent, line)
                    except:
                        pass
                        
            process.wait()
            
            if process.returncode != 0:
                return RipResult(
                    success=False,
                    error_message=f"MakeMKV failed with code {process.returncode}"
                )
                
            # Find the output file
            mkv_files = list(output_dir.glob("*.mkv"))
            if not mkv_files:
                return RipResult(
                    success=False,
                    error_message="No MKV file created"
                )
                
            output_file = max(mkv_files, key=lambda f: f.stat().st_size)
            
            return RipResult(
                success=True,
                output_path=output_file,
                title_info=None  # Could populate this if needed
            )
            
        except Exception as e:
            logger.error(f"Ripping error: {e}")
            return RipResult(success=False, error_message=str(e))
            
    def transcode(
        self,
        input_path: Path,
        output_path: Path,
        progress_callback: Optional[callable] = None
    ) -> RipResult:
        """Transcode the ripped file to final format."""
        config = self.settings.formats
        
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i", str(input_path),
            "-c:v", config.video_codec,
            "-preset", config.preset,
            "-crf", str(config.crf),
            "-c:a", config.audio_codec,
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-stats",
            str(output_path)
        ]
        
        logger.info(f"Transcoding {input_path} -> {output_path}")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            duration = None
            
            for line in process.stdout:
                line = line.strip()
                logger.debug(f"ffmpeg: {line}")
                
                # Parse duration from initial output
                if "Duration:" in line and duration is None:
                    try:
                        time_str = line.split("Duration: ")[1].split(",")[0]
                        h, m, s = time_str.split(":")
                        duration = int(h) * 3600 + int(m) * 60 + float(s)
                    except:
                        pass
                        
                # Parse progress
                if "time=" in line and duration and progress_callback:
                    try:
                        time_str = line.split("time=")[1].split()[0]
                        h, m, s = time_str.split(":")
                        current = int(h) * 3600 + int(m) * 60 + float(s)
                        percent = int((current / duration) * 100)
                        progress_callback("transcoding", percent, line)
                    except:
                        pass
                        
            process.wait()
            
            if process.returncode != 0:
                return RipResult(
                    success=False,
                    error_message=f"FFmpeg failed with code {process.returncode}"
                )
                
            return RipResult(success=True, output_path=output_path)
            
        except Exception as e:
            logger.error(f"Transcoding error: {e}")
            return RipResult(success=False, error_message=str(e))
            
    def process_dvd(
        self,
        device: str,
        output_name: str,
        progress_callback: Optional[callable] = None
    ) -> RipResult:
        """Full pipeline: rip and transcode."""
        try:
            # Step 1: Find main title
            if progress_callback:
                progress_callback("analyzing", 0, "Analyzing disc...")
                
            main_title = self.find_main_title(device)
            if not main_title:
                return RipResult(success=False, error_message="Could not find main title")
                
            title_idx = main_title.index if main_title else 0
            
            # Step 2: Rip
            rip_result = self.rip_title(
                device,
                title_idx,
                progress_callback
            )
            
            if not rip_result.success:
                return rip_result
                
            # Step 3: Transcode
            output_path = self.temp_dir / f"{output_name}.{self.settings.formats.container}"
            transcode_result = self.transcode(
                rip_result.output_path,
                output_path,
                progress_callback
            )
            
            return transcode_result
            
        except Exception as e:
            logger.error(f"Processing error: {e}")
            return RipResult(success=False, error_message=str(e))
            
    def eject_disc(self, device: str) -> bool:
        """Eject the disc from drive."""
        import fcntl
        
        # CDROM ioctl constants
        CDROMEJECT = 0x5309
        
        errors = []
        
        # Method 1: Try using ioctl (most reliable for DVD drives)
        try:
            fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
            try:
                fcntl.ioctl(fd, CDROMEJECT)
                logger.info(f"Ejected disc using ioctl on {device}")
                return True
            finally:
                os.close(fd)
        except Exception as e:
            errors.append(f"ioctl eject: {e}")
        
        # Method 2: Try using eject command
        try:
            result = subprocess.run(
                ["eject", device], 
                check=True, 
                capture_output=True, 
                text=True
            )
            logger.info(f"Ejected disc using eject command on {device}")
            return True
        except Exception as e:
            errors.append(f"eject command: {e}")
        
        # Method 3: Try using sg_start (from sg3-utils) as last resort
        try:
            result = subprocess.run(
                ["sg_start", "--eject", device],
                check=True,
                capture_output=True,
                text=True
            )
            logger.info(f"Ejected disc using sg_start on {device}")
            return True
        except Exception as e:
            errors.append(f"sg_start: {e}")
        
        # All methods failed
        logger.error(f"All eject methods failed for {device}: {'; '.join(errors)}")
        return False
