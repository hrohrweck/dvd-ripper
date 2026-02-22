# DVD Ripper Troubleshooting Guide

This guide helps you debug issues when the DVD ripper isn't working correctly.

## Table of Contents

1. [Quick Diagnostics](#quick-diagnostics)
2. [Common Issues](#common-issues)
3. [Manual Testing Steps](#manual-testing-steps)
4. [Hardware Issues](#hardware-issues)
5. [Software Issues](#software-issues)
6. [Getting Help](#getting-help)

---

## Quick Diagnostics

Run the automated debug script from the host:

```bash
cd /opt/dvd-ripper
./scripts/debug_dvd.sh
```

This will check:
- Container status
- Device accessibility
- Drive status
- MakeMKV functionality
- FFmpeg availability

---

## Common Issues

### 1. "TRAY OPEN" or "NO_DISC" Status

**Symptoms:**
- Debug script shows "Status: TRAY OPEN"
- MakeMKV reports "Failed to open disc"

**Solution:**
1. Insert a DVD into the drive
2. Wait 10-20 seconds for the drive to spin up and read the disc
3. Run the debug script again

### 2. "Permission denied" Errors

**Symptoms:**
- Cannot access `/dev/sr0`
- Drive status check fails with permission error

**Solution:**
Check your `docker-compose.yml` has the correct settings:

```yaml
privileged: true
devices:
  - /dev/sr0:/dev/sr0
cap_add:
  - SYS_ADMIN
  - SYS_RAWIO
volumes:
  - /dev/:/dev
```

Then restart:
```bash
docker-compose down
docker-compose up -d
```

### 3. MakeMKV Timeout / Hangs

**Symptoms:**
- `makemkvcon` command hangs for 60+ seconds
- No output or partial output

**Causes:**
- No disc in drive
- Drive is still initializing/spinning up
- CSS encrypted disc (commercial DVD) without proper decryption
- Drive hardware issues

**Solution:**
1. Ensure disc is inserted and wait 20-30 seconds
2. Try ejecting and re-inserting the disc
3. Check if it's a CSS-encrypted disc (see below)

### 4. CSS/Encryption Errors (Commercial DVDs)

**Symptoms:**
- MakeMKV fails with decryption errors
- "Failed to open disc" on commercial movies

**Solution:**
The container includes libdvdcss which should handle most CSS encryption. If it fails:

```bash
# Enter container
docker exec -it dvd-archive bash

# Install CSS support
/usr/share/doc/libdvdread4/install-css.sh
```

For newer copy protection (Disney, Sony), MakeMKV's built-in decryption usually handles it.

### 5. Celery Worker Not Processing Jobs

**Symptoms:**
- Jobs stuck in "queued" state
- No progress in web UI

**Solution:**
Check Celery worker status:
```bash
# Check if worker is running
docker exec dvd-archive ps aux | grep celery

# View worker logs
docker exec dvd-archive cat /var/log/supervisor/celery-worker.log

# Restart services
docker-compose restart
```

---

## Manual Testing Steps

Test each component individually to isolate the problem:

### Step 1: Verify Device Access

On the **host**:
```bash
# Check device exists
ls -la /dev/sr*

# Check drive status (install sdparm if needed)
sdparm /dev/sr0
```

In the **container**:
```bash
# Check device is accessible
docker exec dvd-archive ls -la /dev/sr0

# Test drive status
docker exec dvd-archive python3 -c "
import os, fcntl
CDROM_DRIVE_STATUS = 0x5326
CDSL_CURRENT = 0x0002
fd = os.open('/dev/sr0', os.O_RDONLY | os.O_NONBLOCK)
status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, CDSL_CURRENT)
print(f'Status code: {status}')
os.close(fd)
"
```

### Step 2: Test MakeMKV

In the **container**:
```bash
# Check MakeMKV version
docker exec dvd-archive makemkvcon --version

# Get disc info (wait up to 2 minutes)
docker exec -it dvd-archive makemkvcon -r info dev:/dev/sr0

# List titles on disc
docker exec -it dvd-archive makemkvcon -r info dev:/dev/sr0 | grep TINFO
```

### Step 3: Test Ripping Process

In the **container**:
```bash
# Create test directory
docker exec dvd-archive mkdir -p /tmp/test_rip

# Try ripping title 0 (main title)
docker exec -it dvd-archive makemkvcon --minlength=600 mkv dev:/dev/sr0 0 /tmp/test_rip

# Check result
docker exec dvd-archive ls -la /tmp/test_rip/
```

### Step 4: Test Transcoding

In the **container**:
```bash
# If you have a test video file
docker exec dvd-archive ffmpeg -i /tmp/test_rip/title00.mkv \
  -c:v libx265 -preset medium -crf 23 \
  -c:a aac -b:a 192k \
  /tmp/test_output.mp4
```

### Step 5: Run Python Tests

The included test script tests all Python components:

```bash
# Run from host
docker exec -it dvd-archive python3 /app/scripts/test_ripper.py full-test

# Or test individual components
docker exec dvd-archive python3 /app/scripts/test_ripper.py drive-status
docker exec dvd-archive python3 /app/scripts/test_ripper.py disc-info
docker exec dvd-archive python3 /app/scripts/test_ripper.py test-rip
```

---

## Hardware Issues

### Drive Not Detected

**Symptoms:**
- `/dev/sr0` doesn't exist
- `ls /dev/sr*` returns "No such file or directory"

**Solutions:**

1. **Check physical connection:**
   - Ensure drive cables are securely connected
   - Try different SATA/USB port

2. **Check kernel recognition:**
   ```bash
   dmesg | grep -i dvd
   dmesg | grep -i sr0
   ```

3. **Load required modules:**
   ```bash
   sudo modprobe sr_mod
   sudo modprobe cdrom
   ```

4. **Check different device names:**
   ```bash
   ls -la /dev/sd*  # Some USB drives show as sdX
   ls -la /dev/cdrom*
   ```

5. **Update docker-compose.yml** if device name is different:
   ```yaml
   devices:
     - /dev/sr1:/dev/sr0  # If your drive is /dev/sr1
   ```

### Drive Keeps Ejecting / Not Reading

**Symptoms:**
- Drive tray opens randomly
- Disc spins but isn't recognized
- Grinding noises

**Solutions:**
1. Clean the laser lens with a cleaning disc
2. Try different discs (some drives are picky about media)
3. Check drive firmware is up to date
4. Test with a known good retail DVD (not a burned disc)

---

## Software Issues

### API Authentication Errors

**Symptoms:**
- `{"detail":"Not authenticated"}`
- Cannot start jobs from web UI

**Solution:**
```bash
# Get auth token
curl -X POST http://localhost:8080/api/token \
  -d "username=admin&password=YOUR_PASSWORD"

# Use token in requests
curl http://localhost:8080/api/drive/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Database Errors

**Symptoms:**
- "Database locked" errors
- Jobs not saving

**Solution:**
```bash
# Check database permissions
docker exec dvd-archive ls -la /app/data/

# Restart to clear locks
docker-compose restart
```

### Redis Connection Errors

**Symptoms:**
- Celery worker fails to start
- "Connection refused" to Redis

**Solution:**
```bash
# Check Redis is running
docker ps | grep redis

# Check Redis logs
docker logs dvd-redis

# Restart Redis
docker-compose restart redis
```

---

## Getting Help

If you've tried the above and still have issues:

1. **Collect debug information:**
   ```bash
   cd /opt/dvd-ripper
   ./scripts/debug_dvd.sh > debug_output.txt 2>&1
   docker logs dvd-archive > container_logs.txt 2>&1
   docker exec dvd-archive cat /var/log/supervisor/celery-worker.log > celery_logs.txt 2>&1
   ```

2. **Check the issue with MakeMKV directly:**
   ```bash
   docker exec -it dvd-archive makemkvcon -r info dev:/dev/sr0
   ```
   If this fails, the issue is with MakeMKV/device access, not the ripper code.

3. **Test with a known-good disc:**
   - Try a different DVD (preferably a recent retail release)
   - Some older or damaged discs may not read properly

4. **Common things to check:**
   - Is the DVD region-free or matching your drive's region?
   - Is the disc clean and unscratched?
   - Does the drive work in another computer/OS?
   - Is the drive getting enough power (for external USB drives)?

---

## Quick Reference Commands

```bash
# Container management
docker-compose up -d          # Start
docker-compose down           # Stop
docker-compose logs -f        # View logs
docker-compose restart        # Restart

# Enter container
docker exec -it dvd-archive bash

# Check services inside container
ps aux | grep -E "(celery|nginx|python)"

# Manual MakeMKV commands
makemkvcon -r info dev:/dev/sr0           # Disc info
makemkvcon --minlength=600 mkv dev:/dev/sr0 0 /output  # Rip main title
makemkvcon --version                      # Version check

# Drive control
eject /dev/sr0        # Eject
eject -t /dev/sr0     # Close tray

# View logs
docker exec dvd-archive cat /var/log/supervisor/celery-worker.log
docker exec dvd-archive cat /var/log/supervisor/fastapi.log
```
