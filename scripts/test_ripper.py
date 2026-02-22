#!/usr/bin/env python3
"""
Test script for DVD ripper components.
Run this inside the container to test individual steps.

Usage:
  docker exec -it dvd-archive python3 /app/scripts/test_ripper.py [command]

Commands:
  drive-status     - Check drive status
  disc-info        - Get disc info using MakeMKV (may take a while)
  test-rip         - Test ripping the main title (dry-run, no actual rip)
  full-test        - Run all tests
  help             - Show this help
"""

import sys
import os
import time
import subprocess
import fcntl

# Add app to path
sys.path.insert(0, '/app')

DEVICE = os.environ.get('DVD_DEVICE', '/dev/sr0')

# CDROM constants
CDROM_DRIVE_STATUS = 0x5326
CDSL_CURRENT = 0x0002
CDS_DISC_OK = 4


def check_drive_status():
    """Check DVD drive status using ioctl."""
    print("=" * 50)
    print("Testing Drive Status Detection")
    print("=" * 50)
    
    if not os.path.exists(DEVICE):
        print(f"❌ ERROR: Device {DEVICE} does not exist!")
        return False
    
    try:
        fd = os.open(DEVICE, os.O_RDONLY | os.O_NONBLOCK)
        try:
            status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, CDSL_CURRENT)
            
            status_map = {
                0: "NO_INFO (drive returned no status)",
                1: "NO_DISC (please insert a DVD)",
                2: "TRAY_OPEN (please close the tray)",
                3: "DRIVE_NOT_READY (drive initializing)",
                4: "DISC_OK (disc ready!)",
            }
            
            status_text = status_map.get(status, f"UNKNOWN ({status})")
            
            if status == CDS_DISC_OK:
                print(f"✅ Drive status: {status_text}")
                return True
            else:
                print(f"⚠️  Drive status: {status_text}")
                return False
                
        finally:
            os.close(fd)
    except PermissionError as e:
        print(f"❌ Permission denied accessing {DEVICE}: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_disc_read():
    """Test reading raw data from disc."""
    print("\n" + "=" * 50)
    print("Testing Raw Disc Read")
    print("=" * 50)
    
    try:
        result = subprocess.run(
            ["dd", f"if={DEVICE}", "of=/dev/null", "bs=2048", "count=1"],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            print("✅ Can read data from disc")
            return True
        else:
            print(f"❌ Cannot read from disc: {result.stderr.decode()}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Timeout reading from disc (no disc or drive busy)")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_makemkv_info():
    """Test MakeMKV disc info."""
    print("\n" + "=" * 50)
    print("Testing MakeMKV Disc Info")
    print("=" * 50)
    print(f"Device: {DEVICE}")
    print("Note: This may take 10-60 seconds for slow drives...")
    print("")
    
    # Check if makemkvcon exists
    result = subprocess.run(["which", "makemkvcon"], capture_output=True)
    if result.returncode != 0:
        print("❌ makemkvcon not found in PATH!")
        return False
    
    print("✅ makemkvcon is installed")
    
    # Get version
    try:
        result = subprocess.run(
            ["makemkvcon", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"Version: {result.stdout.strip()}")
    except:
        pass
    
    # Try to get disc info
    print("\nAttempting to read disc info...")
    try:
        result = subprocess.run(
            ["makemkvcon", "-r", "info", f"dev:{DEVICE}"],
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout
        )
        
        if result.returncode != 0:
            print(f"❌ MakeMKV failed with code {result.returncode}")
            print(f"stderr: {result.stderr}")
            return False
        
        # Parse output
        output = result.stdout
        
        # Look for drive info
        if "Drive Information" in output:
            print("✅ MakeMKV can communicate with drive")
        
        # Count titles
        title_count = output.count("TINFO:")
        if title_count > 0:
            print(f"✅ Found {title_count} titles on disc")
        else:
            print("⚠️  No titles found (may not be a video DVD)")
        
        # Look for disc name
        for line in output.splitlines():
            if line.startswith("CINFO:2,0,"):
                disc_name = line.split(",")[-1].strip('"')
                print(f"✅ Disc name: {disc_name}")
                break
        
        # Show first few lines
        print("\n--- MakeMKV output (first 20 lines) ---")
        for line in output.splitlines()[:20]:
            print(line)
        
        return True
        
    except subprocess.TimeoutExpired:
        print("❌ TIMEOUT: MakeMKV took too long to respond")
        print("   This usually means:")
        print("   - No disc is in the drive")
        print("   - The drive is still spinning up the disc")
        print("   - The drive has a hardware issue")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_ffmpeg():
    """Test FFmpeg availability."""
    print("\n" + "=" * 50)
    print("Testing FFmpeg")
    print("=" * 50)
    
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.splitlines()[0]
            print(f"✅ FFmpeg installed: {version_line}")
            
            # Check for H.265 encoder
            if "libx265" in result.stdout:
                print("✅ H.265 (libx265) encoder available")
            else:
                print("⚠️  H.265 encoder may not be available")
            
            return True
        else:
            print("❌ FFmpeg failed")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_python_modules():
    """Test Python module imports."""
    print("\n" + "=" * 50)
    print("Testing Python Modules")
    print("=" * 50)
    
    modules_ok = True
    
    try:
        from app.ripper import DVDRipper
        print("✅ app.ripper imports successfully")
    except Exception as e:
        print(f"❌ app.ripper import failed: {e}")
        modules_ok = False
    
    try:
        from app.dvd_monitor import create_monitor
        print("✅ app.dvd_monitor imports successfully")
    except Exception as e:
        print(f"❌ app.dvd_monitor import failed: {e}")
        modules_ok = False
    
    try:
        from app.tasks import process_dvd_task
        print("✅ app.tasks imports successfully")
    except Exception as e:
        print(f"❌ app.tasks import failed: {e}")
        modules_ok = False
    
    return modules_ok


def test_ripper_class():
    """Test DVDRipper class initialization."""
    print("\n" + "=" * 50)
    print("Testing DVDRipper Class")
    print("=" * 50)
    
    try:
        from app.ripper import DVDRipper
        
        ripper = DVDRipper()
        print("✅ DVDRipper initialized")
        
        # Test find_main_title (this requires a disc)
        print("\nTesting find_main_title (requires disc)...")
        print("Note: This may take 30-120 seconds...")
        
        title = ripper.find_main_title(DEVICE)
        if title:
            print(f"✅ Found main title: index={title.index}, duration={title.duration_seconds}s, size={title.size_bytes} bytes")
            return True
        else:
            print("⚠️  No main title found (no disc or not a video DVD)")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def show_help():
    """Show help message."""
    print(__doc__)
    print("\nEnvironment variables:")
    print("  DVD_DEVICE    - DVD device path (default: /dev/sr0)")
    print("\nExamples:")
    print("  python3 test_ripper.py drive-status")
    print("  python3 test_ripper.py disc-info")
    print("  DVD_DEVICE=/dev/sr1 python3 test_ripper.py full-test")


def main():
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == "help":
        show_help()
    
    elif command == "drive-status":
        check_drive_status()
    
    elif command == "disc-info":
        check_drive_status()
        test_makemkv_info()
    
    elif command == "test-rip":
        check_drive_status()
        test_ripper_class()
    
    elif command == "full-test":
        print("\n" + "=" * 50)
        print("RUNNING FULL TEST SUITE")
        print("=" * 50)
        
        results = []
        
        results.append(("Drive Status", check_drive_status()))
        results.append(("Disc Read", test_disc_read()))
        results.append(("MakeMKV", test_makemkv_info()))
        results.append(("FFmpeg", test_ffmpeg()))
        results.append(("Python Modules", test_python_modules()))
        
        # Only test ripper if disc is present
        if results[0][1]:
            results.append(("DVDRipper", test_ripper_class()))
        
        print("\n" + "=" * 50)
        print("TEST SUMMARY")
        print("=" * 50)
        
        for name, passed in results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{name}: {status}")
        
        all_passed = all(r[1] for r in results)
        if all_passed:
            print("\n✅ All tests passed! The ripper should work correctly.")
        else:
            print("\n⚠️  Some tests failed. Check the output above for details.")
    
    else:
        print(f"Unknown command: {command}")
        show_help()


if __name__ == "__main__":
    main()
