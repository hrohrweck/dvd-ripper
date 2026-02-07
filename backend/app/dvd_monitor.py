"""DVD Drive Monitoring System."""
import os
import fcntl
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass
import logging

# CDROM ioctl constants
CDROM_DRIVE_STATUS = 0x5326
CDROM_CLEAR_OPTIONS = 0x5321
CDROM_SET_OPTIONS = 0x5320
CDROM_LOCKDOOR = 0x5329
CDSL_CURRENT = 0x0002
CDSL_NONE = 0x0000

# Drive status codes
CDS_NO_INFO = 0
CDS_NO_DISC = 1
CDS_TRAY_OPEN = 2
CDS_DRIVE_NOT_READY = 3
CDS_DISC_OK = 4

logger = logging.getLogger(__name__)


@dataclass
class DiscInfo:
    """Information about a detected disc."""
    device: str
    label: Optional[str] = None
    mount_point: Optional[str] = None
    is_dvd_video: bool = False
    volume_size: int = 0


class DVDMonitor:
    """Monitor DVD drive for disc insertion."""
    
    def __init__(self, device_path: str = "/dev/sr0", poll_interval: float = 2.0):
        self.device_path = device_path
        self.poll_interval = poll_interval
        self._callback: Optional[Callable[[DiscInfo], None]] = None
        self._running = False
        self._last_status: Optional[int] = None
        
    def on_disc_inserted(self, callback: Callable[[DiscInfo], None]):
        """Register callback for disc insertion."""
        self._callback = callback
        
    def _get_drive_status(self) -> int:
        """Get current drive status using ioctl."""
        try:
            fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
            status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, CDSL_CURRENT)
            os.close(fd)
            return status
        except OSError as e:
            logger.error(f"Failed to get drive status: {e}")
            return CDS_NO_INFO
            
    def _is_disc_present(self) -> bool:
        """Check if a disc is present in the drive."""
        status = self._get_drive_status()
        return status == CDS_DISC_OK
        
    def _mount_disc(self) -> Optional[str]:
        """Try to mount the disc and return mount point."""
        try:
            # Create mount point if needed
            mount_point = f"/tmp/dvd_mount_{os.path.basename(self.device_path)}"
            os.makedirs(mount_point, exist_ok=True)
            
            # Try to mount
            result = subprocess.run(
                ["mount", self.device_path, mount_point],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0 or "already mounted" in result.stderr:
                return mount_point
                
            return None
        except Exception as e:
            logger.error(f"Mount failed: {e}")
            return None
            
    def _unmount_disc(self, mount_point: str):
        """Unmount the disc."""
        try:
            subprocess.run(
                ["umount", mount_point],
                capture_output=True,
                check=False
            )
        except Exception as e:
            logger.error(f"Unmount failed: {e}")
            
    def _get_disc_label(self) -> Optional[str]:
        """Get disc label/volume name."""
        try:
            # Try using blkid
            result = subprocess.run(
                ["blkid", "-s", "LABEL", "-o", "value", self.device_path],
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
                
            # Fallback to reading from mounted filesystem
            mount_point = self._mount_disc()
            if mount_point:
                # Try to read from .discinfo or similar
                for info_file in [".discinfo", "discinfo.txt"]:
                    info_path = Path(mount_point) / info_file
                    if info_path.exists():
                        with open(info_path) as f:
                            return f.readline().strip()
                            
            return None
        except Exception as e:
            logger.error(f"Failed to get disc label: {e}")
            return None
            
    def _is_dvd_video_disc(self, mount_point: str) -> bool:
        """Check if mounted disc is a DVD-Video."""
        video_ts = Path(mount_point) / "VIDEO_TS"
        return video_ts.exists() and video_ts.is_dir()
        
    def _get_disc_info(self) -> Optional[DiscInfo]:
        """Get information about the current disc."""
        if not self._is_disc_present():
            return None
            
        mount_point = self._mount_disc()
        if not mount_point:
            return None
            
        try:
            info = DiscInfo(
                device=self.device_path,
                label=self._get_disc_label(),
                mount_point=mount_point,
                is_dvd_video=self._is_dvd_video_disc(mount_point),
                volume_size=self._get_disc_size()
            )
            return info
        finally:
            self._unmount_disc(mount_point)
            
    def _get_disc_size(self) -> int:
        """Get disc size in bytes."""
        try:
            result = subprocess.run(
                ["blockdev", "--getsize64", self.device_path],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception as e:
            logger.error(f"Failed to get disc size: {e}")
        return 0
        
    async def start_monitoring(self):
        """Start monitoring the DVD drive."""
        self._running = True
        logger.info(f"Starting DVD monitor for {self.device_path}")
        
        while self._running:
            try:
                current_status = self._get_drive_status()
                
                # Check if disc was just inserted
                if current_status == CDS_DISC_OK and self._last_status != CDS_DISC_OK:
                    logger.info("Disc detected, waiting for drive to be ready...")
                    await asyncio.sleep(2)  # Wait for disc to settle
                    
                    disc_info = self._get_disc_info()
                    if disc_info and disc_info.is_dvd_video:
                        logger.info(f"DVD-Video detected: {disc_info.label}")
                        if self._callback:
                            await self._trigger_callback(disc_info)
                    elif disc_info:
                        logger.info(f"Non-DVD disc detected: {disc_info.label}")
                        
                self._last_status = current_status
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(self.poll_interval)
                
    async def _trigger_callback(self, disc_info: DiscInfo):
        """Trigger the callback in a safe way."""
        try:
            if asyncio.iscoroutinefunction(self._callback):
                await self._callback(disc_info)
            else:
                self._callback(disc_info)
        except Exception as e:
            logger.error(f"Callback error: {e}")
            
    def stop_monitoring(self):
        """Stop monitoring."""
        self._running = False
        logger.info("DVD monitor stopped")


class UdevDVDMonitor(DVDMonitor):
    """DVD monitor using udev events (more efficient than polling)."""
    
    def __init__(self, device_path: str = "/dev/sr0"):
        super().__init__(device_path)
        self._udev_available = self._check_udev()
        
    def _check_udev(self) -> bool:
        """Check if pyudev is available."""
        try:
            import pyudev
            return True
        except ImportError:
            return False
            
    async def start_monitoring(self):
        """Start monitoring using udev events with polling fallback."""
        if not self._udev_available:
            logger.warning("pyudev not available, falling back to polling")
            await super().start_monitoring()
            return
            
        self._running = True
        logger.info(f"Starting udev DVD monitor for {self.device_path}")
        
        try:
            import pyudev
            context = pyudev.Context()
            
            # Create monitor
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by(subsystem='block', device_type='disk')
            
            # Check initial state
            self._last_status = self._get_drive_status()
            
            # Start monitoring in a separate thread
            loop = asyncio.get_event_loop()
            
            while self._running:
                # Use select for non-blocking monitoring
                import select
                
                if monitor.fileno() >= 0:
                    ready, _, _ = select.select([monitor], [], [], self.poll_interval)
                    
                    if ready:
                        action, device = monitor.receive()
                        
                        if device.device_node == self.device_path:
                            if action == 'change':
                                # Disc inserted or removed
                                await asyncio.sleep(2)  # Wait for mount
                                disc_info = self._get_disc_info()
                                
                                if disc_info and disc_info.is_dvd_video:
                                    logger.info(f"DVD-Video detected via udev: {disc_info.label}")
                                    if self._callback:
                                        await self._trigger_callback(disc_info)
                                        
                # Also poll periodically as a fallback
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Udev monitor error: {e}, falling back to polling")
            await super().start_monitoring()


def create_monitor(device_path: str = "/dev/sr0") -> DVDMonitor:
    """Factory function to create the best available monitor."""
    return UdevDVDMonitor(device_path)
