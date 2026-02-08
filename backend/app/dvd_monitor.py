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
            # Check if device exists
            if not os.path.exists(self.device_path):
                logger.warning(f"Device {self.device_path} does not exist")
                return CDS_NO_INFO
                
            fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, CDSL_CURRENT)
                logger.debug(f"Drive status for {self.device_path}: {status}")
                return status
            finally:
                os.close(fd)
        except PermissionError as e:
            logger.error(f"Permission denied accessing {self.device_path}: {e}")
            return CDS_NO_INFO
        except OSError as e:
            logger.error(f"Failed to get drive status for {self.device_path}: {e}")
            return CDS_NO_INFO
            
    def _is_disc_present(self) -> bool:
        """Check if a disc is present in the drive."""
        status = self._get_drive_status()
        is_present = status == CDS_DISC_OK
        logger.debug(f"Disc present check: status={status}, CDS_DISC_OK={CDS_DISC_OK}, is_present={is_present}")
        return is_present
        
    def _mount_disc(self) -> Optional[str]:
        """Try to mount the disc and return mount point."""
        try:
            # Create mount point if needed
            mount_point = f"/tmp/dvd_mount_{os.path.basename(self.device_path)}"
            os.makedirs(mount_point, exist_ok=True)
            
            # Check if already mounted
            result = subprocess.run(
                ["mountpoint", "-q", mount_point],
                capture_output=True
            )
            if result.returncode == 0:
                logger.debug(f"Mount point {mount_point} is already a mountpoint")
                return mount_point
            
            # Try to mount with udf,iso9660 filesystems (common for DVDs)
            for fs_type in ["udf", "iso9660", "auto"]:
                result = subprocess.run(
                    ["mount", "-t", fs_type, self.device_path, mount_point],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    logger.info(f"Mounted {self.device_path} as {fs_type} at {mount_point}")
                    return mount_point
            
            # Try generic mount as fallback
            result = subprocess.run(
                ["mount", self.device_path, mount_point],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info(f"Mounted {self.device_path} at {mount_point}")
                return mount_point
            else:
                logger.warning(f"Failed to mount {self.device_path}: {result.stderr}")
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
        
    def _is_dvd_video_by_blkid(self) -> bool:
        """Check if disc is DVD-Video using blkid (alternative to mounting)."""
        try:
            result = subprocess.run(
                ["blkid", self.device_path],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                output = result.stdout.lower()
                # UDF filesystem is commonly used for DVD-Video
                if "udf" in output:
                    return True
            return False
        except Exception as e:
            logger.debug(f"blkid check failed: {e}")
            return False
        
    def _get_disc_info(self) -> Optional[DiscInfo]:
        """Get information about the current disc."""
        if not self._is_disc_present():
            logger.debug("No disc present")
            return None
            
        mount_point = self._mount_disc()
        
        try:
            # Try to detect if it's a DVD-Video disc
            is_dvd = False
            if mount_point:
                is_dvd = self._is_dvd_video_disc(mount_point)
                logger.debug(f"VIDEO_TS check result: {is_dvd}")
            
            # Fallback: use blkid to detect UDF filesystem (DVD-Video uses UDF)
            if not is_dvd:
                is_dvd = self._is_dvd_video_by_blkid()
                logger.debug(f"blkid UDF check result: {is_dvd}")
                
            label = self._get_disc_label()
            logger.info(f"Disc at {self.device_path}: label={label}, is_dvd_video={is_dvd}")
            
            info = DiscInfo(
                device=self.device_path,
                label=label,
                mount_point=mount_point,
                is_dvd_video=is_dvd,
                volume_size=self._get_disc_size()
            )
            return info
        except Exception as e:
            logger.error(f"Error getting disc info: {e}")
            return None
        finally:
            if mount_point:
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
        
        # Initialize with current status to detect already-inserted discs
        self._last_status = self._get_drive_status()
        logger.info(f"Initial drive status: {self._last_status} (CDS_DISC_OK={CDS_DISC_OK})")
        
        # Check if disc is already present when monitoring starts
        if self._last_status == CDS_DISC_OK:
            logger.info("Disc already present at startup, detecting...")
            await asyncio.sleep(2)  # Wait for disc to be ready
            disc_info = self._get_disc_info()
            if disc_info and disc_info.is_dvd_video:
                logger.info(f"DVD-Video detected at startup: {disc_info.label}")
                # Ensure disc is unmounted before triggering callback
                # (MakeMKV needs exclusive access)
                self._unmount_disc(f"/tmp/dvd_mount_{os.path.basename(self.device_path)}")
                await asyncio.sleep(1)  # Give time for unmount
                if self._callback:
                    await self._trigger_callback(disc_info)
            elif disc_info:
                logger.info(f"Non-DVD disc detected at startup: {disc_info.label}")
        
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
            await DVDMonitor.start_monitoring(self)
            return
            
        self._running = True
        logger.info(f"Starting udev DVD monitor for {self.device_path}")
        
        try:
            import pyudev
            import select
            context = pyudev.Context()
            
            # Create monitor and start it
            monitor = pyudev.Monitor.from_netlink(context)
            monitor.filter_by(subsystem='block', device_type='disk')
            monitor.start()  # Important: start the monitor before using select
            logger.debug("Udev monitor started successfully")
            
            # Check initial state - important for already-inserted discs
            self._last_status = self._get_drive_status()
            logger.info(f"Initial drive status: {self._last_status} (CDS_DISC_OK={CDS_DISC_OK})")
            
            # Check if disc is already present when monitoring starts
            if self._last_status == CDS_DISC_OK:
                logger.info("Disc already present at startup, detecting...")
                await asyncio.sleep(2)  # Wait for disc to be ready
                disc_info = self._get_disc_info()
                if disc_info and disc_info.is_dvd_video:
                    logger.info(f"DVD-Video detected at startup: {disc_info.label}")
                    if self._callback:
                        await self._trigger_callback(disc_info)
                elif disc_info:
                    logger.info(f"Non-DVD disc detected at startup: {disc_info.label}")
            
            while self._running:
                try:
                    # Use select for non-blocking monitoring
                    if monitor.fileno() >= 0:
                        ready, _, _ = select.select([monitor], [], [], self.poll_interval)
                        
                        if ready:
                            action, device = monitor.receive()
                            
                            if device.device_node == self.device_path:
                                logger.debug(f"Udev event: {action} on {device.device_node}")
                                if action == 'change':
                                    # Disc inserted or removed
                                    await asyncio.sleep(2)  # Wait for disc to settle
                                    disc_info = self._get_disc_info()
                                    
                                    if disc_info and disc_info.is_dvd_video:
                                        logger.info(f"DVD-Video detected via udev: {disc_info.label}")
                                        # Ensure disc is unmounted before triggering callback
                                        self._unmount_disc(f"/tmp/dvd_mount_{os.path.basename(self.device_path)}")
                                        await asyncio.sleep(1)  # Give time for unmount
                                        if self._callback:
                                            await self._trigger_callback(disc_info)
                                    elif disc_info:
                                        logger.info(f"Non-DVD disc detected via udev: {disc_info.label}")
                                            
                    # Also poll periodically as a fallback to catch any missed events
                    await asyncio.sleep(1)
                    
                except Exception as loop_e:
                    logger.error(f"Error in udev monitoring loop: {loop_e}")
                    await asyncio.sleep(self.poll_interval)
                
        except Exception as e:
            logger.error(f"Udev monitor error: {e}, falling back to polling")
            # Don't use super() here, call the parent class method directly
            await DVDMonitor.start_monitoring(self)


def create_monitor(device_path: str = "/dev/sr0") -> DVDMonitor:
    """Factory function to create the best available monitor."""
    return UdevDVDMonitor(device_path)
