"""DVD Ripping and Transcoding Pipeline."""
import os
import subprocess
import tempfile
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import shutil
import re

from app.config import Settings, get_settings
from app.job_manager import job_manager, check_job_cancellation

logger = logging.getLogger(__name__)


@dataclass
class AudioTrack:
    """Information about an audio track."""
    index: int
    codec: str
    language: str
    channels: int
    stream_index: int
    is_main: bool = False
    title: str = ""


@dataclass
class TitleInfo:
    """Information about a DVD title."""
    index: int
    duration_seconds: int
    size_bytes: int
    chapters: int
    audio_tracks: List[AudioTrack] = field(default_factory=list)
    subtitle_tracks: List[Dict] = field(default_factory=list)


@dataclass
class RipResult:
    """Result of ripping operation."""
    success: bool
    output_paths: List[Path] = field(default_factory=list)
    error_message: Optional[str] = None
    title_info: Optional[TitleInfo] = None


class DVDRipper:
    """Handles DVD ripping and transcoding."""
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.temp_dir: Optional[Path] = None
        
    def _create_temp_dir(self) -> Path:
        """Create temporary directory for processing."""
        # Use disk-based storage to avoid RAM limitations
        # /tmp may be tmpfs on some systems, so use /var/tmp for guaranteed disk storage
        temp_base = "/var/tmp" if Path("/var/tmp").exists() else "/tmp"
        self.temp_dir = Path(tempfile.mkdtemp(prefix="dvdrip_", dir=temp_base))
        logger.info(f"Created temp directory: {self.temp_dir}")
        return self.temp_dir
        
    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_dir and self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temp directory: {self.temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {e}")
    
    def _check_tool(self, tool: str) -> bool:
        """Check if a tool is available."""
        result = subprocess.run(["which", tool], capture_output=True)
        return result.returncode == 0
                
    def get_disc_info(self, device: str) -> Dict:
        """Get information about the disc using lsdvd (reliable) or makemkvcon."""
        # Try lsdvd first (more reliable with CSS)
        if self._check_tool("lsdvd"):
            info = self._get_disc_info_lsdvd(device)
            if info and info.get("titles"):
                return info
        
        # Fallback to MakeMKV (may hang on some drives)
        if self._check_tool("makemkvcon"):
            logger.warning("Using MakeMKV fallback - may hang on some drives")
            info = self._get_disc_info_makemkv(device)
            if info and info.get("titles"):
                return info
        
        logger.error("No disc info tool available (lsdvd or makemkvcon)")
        return {}
    
    def _get_disc_info_lsdvd(self, device: str) -> Dict:
        """Get disc info using lsdvd."""
        try:
            logger.info(f"Running lsdvd to get disc info from {device}")
            cmd = ["lsdvd", "-x", "-Oy", device]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60
            )
            
            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace')
                logger.error(f"lsdvd failed: {stderr}")
                return {}
            
            # lsdvd -Oy outputs Python-style dict
            # Decode with 'replace' to handle non-UTF8 bytes from DVD metadata
            output = result.stdout.decode('utf-8', errors='replace')
            return self._parse_lsdvd_output(output)
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout getting disc info with lsdvd")
            return {}
        except Exception as e:
            logger.error(f"Error getting disc info with lsdvd: {e}")
            return {}
    
    def _parse_lsdvd_output(self, output: str) -> Dict:
        """Parse lsdvd -Oy output into a dict."""
        info = {"titles": []}
        
        try:
            # lsdvd -Oy outputs: lsdvd = { ... }
            # Extract the content between outer braces
            if "lsdvd =" in output:
                # Parse as Python literal (safe since lsdvd outputs valid Python literals)
                import ast
                # Remove 'lsdvd = ' prefix and parse
                data_str = output.split("lsdvd =", 1)[1].strip()
                data = ast.literal_eval(data_str)
                
                info["disc_name"] = data.get("title", "Unknown")
                
                for i, track in enumerate(data.get("track", [])):
                    # lsdvd provides length as float seconds
                    length = track.get("length", 0)
                    if isinstance(length, str):
                        length = float(length)
                    
                    # Parse audio tracks
                    audio_tracks = []
                    for j, audio in enumerate(track.get("audio", [])):
                        audio_tracks.append({
                            "index": j,
                            "langcode": audio.get("langcode", "unknown"),
                            "language": audio.get("language", f"Track {j+1}"),
                            "format": audio.get("format", "unknown"),
                            "channels": audio.get("channels", 2),
                        })
                    
                    title = {
                        "index": i,
                        "name": track.get("title", f"Title {i}"),
                        "duration": length,  # In seconds (float)
                        "chapters": len(track.get("chapter", [])),
                        "ix": track.get("ix", 0),  # Title set number
                        "vts": track.get("vts", 0),  # VTS number
                        "ttn": track.get("ttn", 0),  # TTN number
                        "audio": audio_tracks,
                    }
                    info["titles"].append(title)
                
                logger.info(f"Found {len(info['titles'])} titles using lsdvd")
                
        except Exception as e:
            logger.error(f"Error parsing lsdvd output: {e}")
            logger.debug(f"lsdvd output: {output[:500]}")
        
        return info
                
    def _get_disc_info_makemkv(self, device: str) -> Dict:
        """Get disc info using makemkvcon (fallback, may hang)."""
        try:
            logger.info(f"Running makemkvcon to get disc info from {device}")
            cmd = ["makemkvcon", "-r", "info", f"dev:{device}"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # Short timeout since it often hangs
            )
            
            if result.returncode != 0:
                logger.error(f"makemkvcon info failed with code {result.returncode}")
                return {}
            
            parsed = self._parse_makemkv_info(result.stdout)
            logger.info(f"Found {len(parsed.get('titles', []))} titles on disc")
            return parsed
            
        except subprocess.TimeoutExpired:
            logger.error("Timeout getting disc info with makemkvcon (30s) - drive may be slow or disc damaged")
            return {}
        except Exception as e:
            logger.error(f"Error getting disc info with makemkvcon: {e}")
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
        
        # Get duration for each title (handle both string and float)
        def get_duration(t):
            dur = t.get("duration", 0)
            if isinstance(dur, (int, float)):
                return dur
            return self._parse_duration(dur)
        
        # Filter out titles shorter than 10 minutes (600 seconds)
        long_titles = [t for t in titles if get_duration(t) > 600]
        
        if not long_titles:
            # If no long titles, take the longest of all
            long_titles = titles
        
        # Find longest title by duration
        main_title = max(long_titles, key=get_duration)
        
        # Convert audio tracks
        audio_tracks = []
        for i, audio in enumerate(main_title.get("audio", [])):
            audio_tracks.append(AudioTrack(
                index=i,
                codec=audio.get("format", "AC3"),
                language=audio.get("langcode", audio.get("language", f"track{i}")),
                channels=audio.get("channels", 2),
                stream_index=i,
                title=audio.get("language", f"Track {i+1}")
            ))
        
        return TitleInfo(
            index=main_title["index"],
            duration_seconds=int(get_duration(main_title)),
            size_bytes=0,  # lsdvd doesn't provide size
            chapters=int(main_title.get("chapters", 0)),
            audio_tracks=audio_tracks,
            subtitle_tracks=[]
        )
        
    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string to seconds."""
        try:
            # Handle formats like "01:23:45.123" or "1:23:45"
            parts = duration_str.split(":")
            if len(parts) >= 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return int(hours * 3600 + minutes * 60 + seconds)
            elif len(parts) == 2:
                minutes = int(parts[0])
                seconds = float(parts[1])
                return int(minutes * 60 + seconds)
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
    
    def _probe_audio_tracks(self, vob_files: List[Path]) -> List[Dict]:
        """Use ffprobe to detect all audio tracks in VOB files."""
        if not vob_files:
            return []
        
        # Use the first VOB file for probing
        first_vob = vob_files[0]
        
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "stream=index,codec_name,codec_type,channels:stream_tags=language,title",
                "-of", "json",
                str(first_vob)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                logger.error(f"ffprobe failed: {result.stderr}")
                return []
            
            probe_data = json.loads(result.stdout)
            audio_tracks = []
            
            for stream in probe_data.get("streams", []):
                if stream.get("codec_type") == "audio":
                    tags = stream.get("tags", {})
                    audio_tracks.append({
                        "index": stream.get("index"),
                        "codec": stream.get("codec_name", "unknown"),
                        "channels": stream.get("channels", 2),
                        "language": tags.get("language", "und"),
                        "title": tags.get("title", ""),
                    })
            
            logger.info(f"Detected {len(audio_tracks)} audio tracks: {[a['language'] for a in audio_tracks]}")
            return audio_tracks
            
        except Exception as e:
            logger.error(f"Error probing audio tracks: {e}")
            return []
        
    def rip_title(
        self,
        device: str,
        title_index: int = 0,
        progress_callback: Optional[callable] = None,
        job_id: Optional[int] = None
    ) -> RipResult:
        """Rip a specific title from the DVD."""
        temp_dir = self._create_temp_dir()
        output_dir = temp_dir / "rip"
        output_dir.mkdir()
        
        # Register job with manager if job_id provided
        if job_id:
            job_manager.register_job(job_id)
        
        # Try dvdbackup first (more reliable with CSS)
        if self._check_tool("dvdbackup"):
            return self._rip_with_dvdbackup(device, title_index, output_dir, progress_callback, job_id)
        
        # Fallback to MakeMKV
        if self._check_tool("makemkvcon"):
            logger.warning("Using MakeMKV fallback for ripping")
            return self._rip_with_makemkv(device, title_index, output_dir, progress_callback)
        
        return RipResult(success=False, error_message="No ripping tool available (dvdbackup or makemkvcon)")
    
    def _rip_with_dvdbackup(
        self,
        device: str,
        title_index: int,
        output_dir: Path,
        progress_callback: Optional[callable] = None,
        job_id: Optional[int] = None
    ) -> RipResult:
        """Rip using dvdbackup + ffmpeg with proper audio track handling."""
        try:
            # Title index in lsdvd starts from 0, but dvdbackup uses 1-based
            dvdbackup_title = title_index + 1
            
            logger.info(f"Ripping title {title_index} (dvdbackup title {dvdbackup_title}) from {device}")
            if progress_callback:
                progress_callback("ripping", 0, "Starting dvdbackup...")
            
            # Create a temp directory for dvdbackup output
            backup_dir = output_dir / "dvd"
            backup_dir.mkdir()
            
            # Run dvdbackup to rip the specific title
            cmd = [
                "dvdbackup",
                "-i", device,
                "-o", str(backup_dir),
                "-t", str(dvdbackup_title),  # Specific title
                "-n", "movie"  # DVD name
            ]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Register process with job manager if job_id provided
            if job_id:
                job_manager.register_process(job_id, process)
            
            # Monitor progress with timeout to avoid blocking forever
            import select
            while True:
                # Check if process has finished
                ret = process.poll()
                if ret is not None:
                    break
                
                # Check for cancellation
                if job_id and check_job_cancellation(job_id):
                    logger.info(f"Job {job_id} cancelled, terminating dvdbackup")
                    process.terminate()
                    time.sleep(1)
                    if process.poll() is None:
                        process.kill()
                    return RipResult(success=False, error_message="Job cancelled by user")
                
                # Read available output (non-blocking)
                readable, _, _ = select.select([process.stdout], [], [], 1.0)
                if readable:
                    try:
                        line = process.stdout.readline()
                        if line:
                            line = line.strip()
                            logger.debug(f"dvdbackup: {line}")
                            if progress_callback:
                                progress_callback("ripping", 50, line)
                    except:
                        pass
                
                time.sleep(0.1)
            
            # Check if process was cancelled after completion
            if job_id and check_job_cancellation(job_id):
                return RipResult(success=False, error_message="Job cancelled by user")
            
            if process.returncode != 0:
                return RipResult(
                    success=False,
                    error_message=f"dvdbackup failed with code {process.returncode}"
                )
            
            if progress_callback:
                progress_callback("ripping", 100, "dvdbackup complete")
            
            # Find the VIDEO_TS directory
            video_ts_dirs = list(backup_dir.rglob("VIDEO_TS"))
            if not video_ts_dirs:
                return RipResult(
                    success=False,
                    error_message="No VIDEO_TS directory found after ripping"
                )
            
            video_ts = video_ts_dirs[0]
            
            # Find all VOB files for this title
            vob_files = sorted(video_ts.glob(f"VTS_*{dvdbackup_title:02d}_*.VOB"))
            if not vob_files:
                # Try without specific pattern
                vob_files = sorted(video_ts.glob("*.VOB"))
            
            if not vob_files:
                return RipResult(
                    success=False,
                    error_message="No VOB files found"
                )
            
            logger.info(f"Found {len(vob_files)} VOB files")
            
            # Create concat file for ffmpeg
            concat_file = output_dir / "concat.txt"
            with open(concat_file, "w") as f:
                for vob in vob_files:
                    # Escape single quotes in path
                    path = str(vob).replace("'", "'\\''")
                    f.write(f"file '{path}'\n")
            
            # Probe audio tracks from VOB files
            if progress_callback:
                progress_callback("analyzing", 0, "Detecting audio tracks...")
            
            audio_tracks = self._probe_audio_tracks(vob_files)
            
            if not audio_tracks:
                logger.warning("No audio tracks detected, falling back to default behavior")
                audio_tracks = [{"index": 1, "codec": "ac3", "language": "eng", "channels": 2, "title": ""}]
            
            # Log detected audio tracks
            logger.info(f"Detected {len(audio_tracks)} audio track(s):")
            for track in audio_tracks:
                logger.info(f"  Track {track['index']}: {track['language']} ({track['codec']}, {track['channels']}ch) - {track.get('title', '')}")
            
            # Check for cancellation before starting ffmpeg
            if job_id and check_job_cancellation(job_id):
                return RipResult(success=False, error_message="Job cancelled by user")
            
            # Generate output files - one per audio track
            output_files = []
            
            for track_idx, audio_track in enumerate(audio_tracks):
                # Determine language code
                lang_code = audio_track.get('language', 'und')
                if lang_code == 'und' or not lang_code:
                    lang_code = f'track{track_idx+1}'
                
                # Create output filename with language code
                mkv_output = output_dir / f"movie_{lang_code}.mkv"
                
                if progress_callback:
                    progress_callback("transcoding", int((track_idx / len(audio_tracks)) * 100), 
                                    f"Converting audio track {track_idx+1}/{len(audio_tracks)} ({lang_code})...")
                
                # Build ffmpeg command for this audio track
                # Map video and the specific audio track
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-hide_banner",
                    "-y",
                    "-fflags", "+genpts",  # Generate presentation timestamps for VOB files
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_file),
                ]
                
                # Map video stream
                ffmpeg_cmd.extend(["-map", "0:v:0"])
                
                # Map specific audio stream
                audio_stream_idx = audio_track['index']
                ffmpeg_cmd.extend(["-map", f"0:a:{track_idx}"])
                
                # Audio codec settings - copy for original quality
                ffmpeg_cmd.extend([
                    "-c:v", "copy",  # Copy video as-is
                    "-c:a", "copy",  # Copy audio as-is to preserve quality
                ])
                
                # Add metadata
                ffmpeg_cmd.extend([
                    "-metadata:s:a:0", f"language={lang_code}",
                    "-metadata:s:a:0", f"title={audio_track.get('title', lang_code)}",
                ])
                
                ffmpeg_cmd.append(str(mkv_output))
                
                logger.info(f"Creating {mkv_output} with audio track {track_idx} ({lang_code})")
                
                # Run ffmpeg with cancellation support
                ffmpeg_process = subprocess.Popen(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                # Register with job manager
                if job_id:
                    job_manager.register_process(job_id, ffmpeg_process)
                
                # Monitor ffmpeg output
                for line in ffmpeg_process.stdout:
                    line = line.strip()
                    if progress_callback:
                        progress_callback("transcoding", int((track_idx / len(audio_tracks)) * 100), line)
                    
                    # Check for cancellation
                    if job_id and check_job_cancellation(job_id):
                        logger.info(f"Job {job_id} cancelled, terminating ffmpeg")
                        ffmpeg_process.terminate()
                        time.sleep(1)
                        if ffmpeg_process.poll() is None:
                            ffmpeg_process.kill()
                        return RipResult(success=False, error_message="Job cancelled by user")
                
                ffmpeg_process.wait()
                ffmpeg_returncode = ffmpeg_process.returncode
                
                if ffmpeg_returncode != 0:
                    logger.error(f"ffmpeg failed for track {track_idx}")
                    # Check if it was cancelled
                    if job_id and check_job_cancellation(job_id):
                        return RipResult(success=False, error_message="Job cancelled by user")
                    continue
                
                if mkv_output.exists() and mkv_output.stat().st_size > 0:
                    output_files.append(mkv_output)
                    logger.info(f"Created {mkv_output} ({mkv_output.stat().st_size // 1024 // 1024} MB)")
                else:
                    logger.error(f"Output file {mkv_output} was not created or is empty")
            
            if not output_files:
                return RipResult(
                    success=False,
                    error_message="No output files were created"
                )
            
            logger.info(f"Successfully created {len(output_files)} output file(s)")
            return RipResult(success=True, output_paths=output_files)
            
        except subprocess.TimeoutExpired:
            return RipResult(success=False, error_message="dvdbackup or ffmpeg timed out")
        except Exception as e:
            logger.error(f"dvdbackup ripping error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return RipResult(success=False, error_message=str(e))
    
    def _rip_with_makemkv(
        self,
        device: str,
        title_index: int,
        output_dir: Path,
        progress_callback: Optional[callable] = None
    ) -> RipResult:
        """Rip using MakeMKV (fallback, may hang)."""
        try:
            cmd = [
                "makemkvcon",
                "--minlength=600",
                "--noscan",
                "mkv",
                f"dev:{device}",
                str(title_index),
                str(output_dir)
            ]
            
            logger.info(f"Ripping title {title_index} from {device} using MakeMKV")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            for line in process.stdout:
                line = line.strip()
                logger.debug(f"makemkvcon: {line}")
                
                if "Progress" in line and progress_callback:
                    try:
                        percent = int(line.split("%")[0].split()[-1])
                        progress_callback("ripping", percent, line)
                    except:
                        pass
                        
            process.wait(timeout=600)  # 10 minute timeout
            
            if process.returncode != 0:
                return RipResult(
                    success=False,
                    error_message=f"MakeMKV failed with code {process.returncode}"
                )
                
            mkv_files = list(output_dir.glob("*.mkv"))
            if not mkv_files:
                return RipResult(
                    success=False,
                    error_message="No MKV file created"
                )
                
            output_file = max(mkv_files, key=lambda f: f.stat().st_size)
            return RipResult(success=True, output_paths=[output_file])
            
        except subprocess.TimeoutExpired:
            process.kill()
            return RipResult(success=False, error_message="MakeMKV timed out (10 minutes)")
        except Exception as e:
            logger.error(f"MakeMKV ripping error: {e}")
            return RipResult(success=False, error_message=str(e))
    
    def transcode(
        self,
        input_paths: List[Path],
        output_name: str,
        progress_callback: Optional[callable] = None
    ) -> RipResult:
        """Transcode the ripped files to final format."""
        config = self.settings.formats
        output_files = []
        
        for idx, input_path in enumerate(input_paths):
            # Extract language from filename (movie_LANG.mkv)
            lang_match = re.search(r'movie_([a-zA-Z0-9]+)\.mkv$', input_path.name)
            lang_suffix = lang_match.group(1) if lang_match else f"track{idx+1}"
            
            output_path = self.temp_dir / f"{output_name}_{lang_suffix}.{config.container}"
            
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
            
            logger.info(f"Transcoding {input_path} ({lang_suffix}) -> {output_path}")
            
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
                    
                    if "Duration:" in line and duration is None:
                        try:
                            time_str = line.split("Duration: ")[1].split(",")[0]
                            h, m, s = time_str.split(":")
                            duration = int(h) * 3600 + int(m) * 60 + float(s)
                        except:
                            pass
                            
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
                    logger.error(f"FFmpeg failed for {lang_suffix}")
                    continue
                    
                output_files.append(output_path)
                logger.info(f"Transcoded {lang_suffix}: {output_path}")
                
            except Exception as e:
                logger.error(f"Transcoding error for {input_path}: {e}")
                continue
        
        if not output_files:
            return RipResult(success=False, error_message="All transcoding operations failed")
            
        return RipResult(success=True, output_paths=output_files)
            
    def process_dvd(
        self,
        device: str,
        output_name: str,
        progress_callback: Optional[callable] = None,
        job_id: Optional[int] = None
    ) -> RipResult:
        """Full pipeline: rip and transcode."""
        try:
            # Step 1: Find main title
            if progress_callback:
                progress_callback("analyzing", 0, "Analyzing disc...")
                
            main_title = self.find_main_title(device)
            if not main_title:
                return RipResult(success=False, error_message="Could not find main title")
                
            title_idx = main_title.index
            logger.info(f"Selected main title: index={title_idx}, duration={main_title.duration_seconds}s")
            logger.info(f"Audio tracks available: {len(main_title.audio_tracks)}")
            for track in main_title.audio_tracks:
                logger.info(f"  - {track.language} ({track.codec})")
            
            # Step 2: Rip
            rip_result = self.rip_title(
                device,
                title_idx,
                progress_callback,
                job_id
            )
            
            if not rip_result.success:
                return rip_result
            
            logger.info(f"Rip complete. Created {len(rip_result.output_paths)} file(s):")
            for path in rip_result.output_paths:
                logger.info(f"  - {path}")
                
            # Step 3: Transcode each file
            transcode_result = self.transcode(
                rip_result.output_paths,
                output_name,
                progress_callback
            )
            
            return transcode_result
            
        except Exception as e:
            logger.error(f"Processing error: {e}")
            import traceback
            logger.error(traceback.format_exc())
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
