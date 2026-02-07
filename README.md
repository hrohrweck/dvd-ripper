# DVD Auto-Ripper & Archive System

A complete Docker-based solution for automatically ripping DVDs, transcoding them to efficient formats (H.265), fetching metadata, and organizing your movie library.

## Features

- **Automatic DVD Detection**: Monitors DVD drive for disc insertion
- **Smart Ripping**: Uses MakeMKV to rip DVDs with automatic main title detection
- **Hardware-Accelerated Transcoding**: FFmpeg with H.265/HEVC support
- **Metadata Fetching**: Automatically fetches movie information from TMDB and OMDB
- **Web Interface**: React-based UI for monitoring and management
- **Library Management**: Browse, search, and manage your archived movies
- **Job Queue**: Track ripping progress in real-time
- **Multiple Storage Options**: Local filesystem or SSH/SFTP transfer

## Quick Start

### Prerequisites

- Docker and Docker Compose
- DVD drive accessible at `/dev/sr0`
- Linux host (for device passthrough)

### Installation

1. **Clone and configure:**
```bash
git clone <repository> /opt/dvd-ripper
cd /opt/dvd-ripper
cp .env.example .env
```

2. **Edit `.env` with your settings:**
```bash
# Required
SECRET_KEY=your-secret-key-here

# Optional - for metadata
TMDB_API_KEY=your-tmdb-api-key
OMDB_API_KEY=your-omdb-api-key
```

3. **Build and start:**
```bash
docker-compose up -d
```

4. **Complete setup:**
Navigate to `http://your-server:8080` and complete the initial setup wizard.

## Usage

### Automatic Ripping

1. Insert a DVD into the drive
2. The system will automatically detect and start ripping
3. Monitor progress via the web interface
4. The disc will be ejected when complete

### Manual Ripping

1. Go to Dashboard
2. Click "Start Ripping" when a disc is detected
3. Or use the Queue page to manage jobs

### Library Management

- Browse your archived movies in the Library view
- Click on any movie to view details
- Delete entries or files as needed

### Configuration

Access the Settings page to configure:

- **Output Format**: Video codec, quality (CRF), preset
- **Storage**: Local path or SSH destination
- **API Keys**: TMDB and OMDB for metadata
- **Device**: DVD drive path

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   DVD        │  │   Backend    │  │   Web Interface  │  │
│  │   Monitor    │  │   (Python)   │  │   (React)        │  │
│  │   (udev/     │  │   FastAPI    │  │   Nginx          │  │
│  │   polling)   │  │   Celery     │  │                  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────┘  │
│         │                 │                                  │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────────────────┐  │
│  │   MakeMKV/   │  │   FFmpeg     │  │   SQLite         │  │
│  │   HandBrake  │  │   (h265)     │  │   (Metadata DB)  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| Web UI | 8080 | Main web interface |
| Flower | 8080/flower | Celery monitoring |
| API | 80/api | FastAPI backend |

## Project Structure

```
dvd-ripper/
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile              # Main container image
├── .env                    # Environment variables
├── README.md               # This file
├── backend/                # Python backend
│   ├── app/
│   │   ├── main.py         # FastAPI entry point
│   │   ├── config.py       # Configuration management
│   │   ├── database.py     # SQLModel database models
│   │   ├── auth.py         # JWT authentication
│   │   ├── dvd_monitor.py  # DVD drive monitoring
│   │   ├── ripper.py       # DVD ripping pipeline
│   │   ├── tasks.py        # Celery background tasks
│   │   └── metadata/       # TMDB/OMDB clients
│   └── requirements.txt    # Python dependencies
├── frontend/               # React frontend
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── App.jsx         # Main app component
│   │   └── styles.css      # Styles
│   └── package.json
├── scripts/                # Initialization scripts
│   ├── init.sh             # Container entrypoint
│   └── supervisor.conf     # Process manager config
├── config/                 # Configuration storage
└── storage/                # Default archive location
```

## API Endpoints

### Authentication
- `POST /api/token` - Login

### Library
- `GET /api/library` - List all movies
- `GET /api/library/{id}` - Get movie details
- `DELETE /api/library/{id}` - Delete movie

### Jobs
- `GET /api/jobs` - List jobs
- `POST /api/jobs` - Start new rip job
- `GET /api/jobs/{id}` - Get job status
- `DELETE /api/jobs/{id}` - Cancel job

### Configuration
- `GET /api/config` - Get configuration
- `POST /api/config` - Update configuration

### Drive
- `GET /api/drive/status` - Get drive status
- `POST /api/drive/eject` - Eject drive

### Metadata
- `GET /api/metadata/search?q={query}` - Search movies
- `GET /api/metadata/{provider}/{id}` - Get movie details

## Troubleshooting

### Drive not detected
```bash
# Check device exists
ls -la /dev/sr*

# Check permissions
docker exec dvd-archive ls -la /dev/sr0
```

### MakeMKV license
MakeMKV runs in trial mode by default. For permanent use, purchase a license from the MakeMKV website.

### Slow ripping
- Use tmpfs for temp storage (enabled by default)
- Enable hardware acceleration in settings
- Check CPU usage with `docker stats`

### SSH transfer issues
```bash
# Test SSH from container
docker exec -it dvd-archive ssh -i /path/to/key user@host
```

## Development

### Backend Development
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev
```

## License

MIT License - See LICENSE file

## Acknowledgments

- [MakeMKV](https://www.makemkv.com/) - DVD ripping
- [FFmpeg](https://ffmpeg.org/) - Video transcoding
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [Celery](https://docs.celeryproject.org/) - Task queue
- [TMDB](https://www.themoviedb.org/) - Movie metadata
