FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # MakeMKV dependencies
    build-essential \
    pkg-config \
    libc6-dev \
    libssl-dev \
    libexpat1-dev \
    libavcodec-dev \
    libgl1-mesa-dev \
    qtbase5-dev \
    # FFmpeg and DVD tools
    ffmpeg \
    libdvd-pkg \
    libdvdnav4 \
    libdvdread8 \
    libbluray2 \
    # Device management
    udev \
    sg3-utils \
    eject \
    # Python environment
    python3.11 \
    python3-pip \
    python3-venv \
    python3-dev \
    # Web server
    nginx \
    supervisor \
    curl \
    wget \
    git \
    ca-certificates \
    gnupg \
    && dpkg-reconfigure -f noninteractive libdvd-pkg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x (required for Vite)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Build MakeMKV from source (bin and oss)
# Note: Check https://www.makemkv.com/download/ for the latest version
ARG MAKEMKV_VERSION=1.18.3
RUN mkdir -p /tmp/makemkv && cd /tmp/makemkv && \
    wget https://www.makemkv.com/download/makemkv-bin-${MAKEMKV_VERSION}.tar.gz && \
    wget https://www.makemkv.com/download/makemkv-oss-${MAKEMKV_VERSION}.tar.gz && \
    tar xzf makemkv-oss-${MAKEMKV_VERSION}.tar.gz && \
    tar xzf makemkv-bin-${MAKEMKV_VERSION}.tar.gz && \
    cd makemkv-oss-${MAKEMKV_VERSION} && \
    ./configure && make && make install && \
    cd ../makemkv-bin-${MAKEMKV_VERSION} && \
    mkdir -p tmp && \
    echo "accepted" > tmp/eula_accepted && \
    make install && \
    cd / && rm -rf /tmp/makemkv

# Setup Python environment
WORKDIR /app
COPY backend/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Build frontend
COPY frontend/ /tmp/frontend/
WORKDIR /tmp/frontend
RUN npm install && npm run build && \
    mkdir -p /var/www/html && \
    cp -r dist/* /var/www/html/ && \
    rm -rf /tmp/frontend

# Setup backend
WORKDIR /app
COPY backend/ /app/
COPY scripts/init.sh /app/
COPY scripts/supervisor.conf /etc/supervisor/conf.d/
COPY scripts/nginx.conf /etc/nginx/sites-available/default

# Create necessary directories
RUN mkdir -p /app/data /app/config /archive /var/log/supervisor && \
    chmod +x /app/init.sh

# Set up permissions for optical drive
RUN groupadd -r optical && usermod -a -G optical www-data

# Expose ports
EXPOSE 80 5555

# Start services
CMD ["/app/init.sh"]
