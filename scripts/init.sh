#!/bin/bash
set -e

CONFIG_FILE="/app/config/settings.yml"
FIRST_RUN_FLAG="/app/.first_run"

echo "=========================================="
echo "  DVD Ripper - Initialization Script"
echo "=========================================="

# Create necessary directories
mkdir -p /app/data /app/config /archive /var/log/supervisor /var/log/nginx

# Check if this is first run
if [ ! -f "$CONFIG_FILE" ]; then
    echo "First run detected - creating default configuration"
    touch "$FIRST_RUN_FLAG"
    
    # Create default config
    cat > "$CONFIG_FILE" <<'EOF'
database:
  url: sqlite:///app/data/dvdrip.db

formats:
  video_codec: libx265
  audio_codec: aac
  container: mp4
  crf: 23
  preset: medium

destination:
  type: local
  local:
    path: /archive
  ssh:
    host: ""
    user: ""
    key_path: ""
    remote_path: ""

metadata:
  providers:
    - tmdb
    - omdb
  api_keys:
    tmdb: ""
    omdb: ""

server:
  port: 80
  auth_enabled: true
  cors_origins:
    - "*"

dvd_device: /dev/sr0
EOF
    echo "Default configuration created at $CONFIG_FILE"
else
    echo "Using existing configuration"
    if [ -f "$FIRST_RUN_FLAG" ]; then
        rm "$FIRST_RUN_FLAG"
    fi
fi

# Set permissions for optical drive access
echo "Setting up optical drive permissions..."
if [ -e /dev/sr0 ]; then
    chmod 666 /dev/sr0 2>/dev/null || true
fi

# Setup DVD decryption if needed
if [ -f /usr/share/doc/libdvdread4/install-css.sh ]; then
    echo "Setting up DVD CSS decryption..."
    /usr/share/doc/libdvdread4/install-css.sh 2>/dev/null || true
fi

# Create default nginx config if not exists
if [ ! -f /etc/nginx/sites-available/default ]; then
    echo "Creating nginx configuration..."
    cat > /etc/nginx/sites-available/default <<'EOF'
server {
    listen 80;
    server_name localhost;
    root /var/www/html;
    index index.html;

    # Frontend - React SPA
    location / {
        try_files $uri $uri/ /index.html;
        expires 1h;
        add_header Cache-Control "public, immutable";
    }

    # Backend API
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 86400;
    }

    # Flower (Celery monitoring)
    location /flower/ {
        proxy_pass http://localhost:5555/flower/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Static assets
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
EOF
fi

echo ""
echo "Starting services..."
echo ""

# Start supervisord which manages all services
exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisor.conf
