#!/bin/bash
# DVD Ripper Debug Script
# This script helps debug DVD ripping issues by testing each component

set -e

DEVICE="${1:-/dev/sr0}"
CONTAINER="${CONTAINER_NAME:-dvd-archive}"

echo "=========================================="
echo "  DVD Ripper Debug Script"
echo "=========================================="
echo "Device: $DEVICE"
echo "Container: $CONTAINER"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check if running from host or container
if [ -f /app/init.sh ]; then
    print_error "This script should be run from the HOST, not inside the container"
    exit 1
fi

# Check if docker is available
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed or not in PATH"
    exit 1
fi

# Check if container is running
echo "--- Checking Container Status ---"
if docker ps | grep -q "$CONTAINER"; then
    print_status "Container '$CONTAINER' is running"
else
    print_error "Container '$CONTAINER' is not running!"
    echo "Start it with: docker-compose up -d"
    exit 1
fi

# Check if device exists on host
echo ""
echo "--- Checking DVD Device on Host ---"
if [ -e "$DEVICE" ]; then
    print_status "Device $DEVICE exists on host"
    ls -la "$DEVICE"
else
    print_error "Device $DEVICE does NOT exist on host!"
    echo "Available optical devices:"
    ls -la /dev/sr* 2>/dev/null || echo "No /dev/sr* devices found"
    ls -la /dev/cdrom* 2>/dev/null || echo "No /dev/cdrom* devices found"
    exit 1
fi

# Check if device is accessible inside container
echo ""
echo "--- Checking DVD Device in Container ---"
if docker exec "$CONTAINER" ls -la "$DEVICE" &>/dev/null; then
    print_status "Device $DEVICE is accessible inside container"
    docker exec "$CONTAINER" ls -la "$DEVICE"
else
    print_error "Device $DEVICE is NOT accessible inside container!"
    echo "Check your docker-compose.yml has the device mapping:"
    echo "  devices:"
    echo "    - \"/dev/sr0:/dev/sr0\""
    exit 1
fi

# Test drive status detection
echo ""
echo "--- Testing Drive Status Detection ---"
echo "Attempting to read drive status..."
docker exec "$CONTAINER" python3 -c "
import os
import fcntl

CDROM_DRIVE_STATUS = 0x5326
CDSL_CURRENT = 0x0002
CDS_DISC_OK = 4

try:
    fd = os.open('$DEVICE', os.O_RDONLY | os.O_NONBLOCK)
    try:
        status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, CDSL_CURRENT)
        print(f'Drive status code: {status}')
        if status == CDS_DISC_OK:
            print('Status: DISC PRESENT (ready to rip)')
        elif status == 1:
            print('Status: NO DISC (please insert a DVD)')
        elif status == 2:
            print('Status: TRAY OPEN (please close the tray)')
        elif status == 3:
            print('Status: DRIVE NOT READY (drive may be initializing)')
        else:
            print(f'Status: Unknown code {status}')
    finally:
        os.close(fd)
except Exception as e:
    print(f'ERROR: {e}')
    exit(1)
" 2>&1

# Test if disc can be read
echo ""
echo "--- Testing Disc Read Access ---"
echo "Trying to read first few sectors from disc (this may take 10-30 seconds)..."
docker exec "$CONTAINER" bash -c "
if dd if=$DEVICE of=/dev/null bs=2048 count=1 2>/dev/null; then
    echo 'SUCCESS: Can read data from disc'
    exit 0
else
    echo 'FAILED: Cannot read from disc (no disc or drive issue)'
    exit 1
fi
" 2>&1 || print_warning "Could not read from disc - may be empty or not ready"

# Test makemkvcon availability
echo ""
echo "--- Testing MakeMKV ---"
if docker exec "$CONTAINER" which makemkvcon &>/dev/null; then
    print_status "makemkvcon is installed"
    docker exec "$CONTAINER" makemkvcon --version 2>&1 | head -2 || true
else
    print_error "makemkvcon is NOT installed!"
fi

# Test makemkvcon disc info (with timeout)
echo ""
echo "--- Testing MakeMKV Disc Detection ---"
echo "This will attempt to read disc info (timeout: 60 seconds)..."
echo "If this hangs, there may be no disc or a hardware issue."
echo ""

timeout 60 docker exec "$CONTAINER" bash -c "
# Try to detect disc info
makemkvcon -r info dev:$DEVICE 2>&1 | head -50
" && print_status "MakeMKV can read disc" || print_warning "MakeMKV timed out or failed - disc may not be present or CSS encrypted"

# Test ffmpeg
echo ""
echo "--- Testing FFmpeg ---"
if docker exec "$CONTAINER" which ffmpeg &>/dev/null; then
    print_status "ffmpeg is installed"
    docker exec "$CONTAINER" ffmpeg -version 2>&1 | head -1
else
    print_error "ffmpeg is NOT installed!"
fi

# Check container logs for errors
echo ""
echo "--- Checking Recent Container Logs ---"
docker logs --tail 30 "$CONTAINER" 2>&1 | tail -30

# Summary
echo ""
echo "=========================================="
echo "  Debug Summary"
echo "=========================================="
echo ""
echo "If MakeMKV timed out above:"
echo "  1. Make sure a DVD is inserted in the drive"
echo "  2. Wait for the drive light to stop blinking (disc spinning up)"
echo "  3. Run this script again"
echo ""
echo "If you see CSS/encryption errors:"
echo "  - Commercial DVDs are encrypted and may need libdvdcss"
echo "  - Check if /usr/share/doc/libdvdread4/install-css.sh exists in container"
echo ""
echo "To manually test ripping:"
echo "  1. Insert a DVD and wait 10-20 seconds for it to spin up"
echo "  2. Run: docker exec -it $CONTAINER bash"
echo "  3. Then: makemkvcon -r info dev:$DEVICE"
echo ""
echo "To check Celery worker logs:"
echo "  docker exec $CONTAINER cat /var/log/supervisor/celery-worker.log"
echo ""
echo "To trigger a rip job manually via API:"
echo "  # Get auth token first (replace USERNAME and PASSWORD):"
echo "  TOKEN=\$(curl -s -X POST http://localhost:8080/api/token \\"
echo "    -d 'username=admin&password=YOUR_PASSWORD' | grep -oP 'access_token\":\"\K[^\"]+')"
echo "  curl -X POST http://localhost:8080/api/jobs \\"
echo "    -H \"Authorization: Bearer \$TOKEN\" \\"
echo "    -d 'device=/dev/sr0'"
echo ""
