# wa_automate

![CI](https://github.com/yonatan/wa_automate/workflows/CI/badge.svg)
[![codecov](https://codecov.io/gh/yonatan/wa_automate/branch/main/graph/badge.svg)](https://codecov.io/gh/yonatan/wa_automate)

Automated WhatsApp media backup with face recognition filtering.

## Overview

`wa_automate` monitors WhatsApp media directories, identifies photos containing known faces using face recognition, and automatically uploads matching images to Google Photos.

## Features

- **Face Recognition**: Supports two backends:
  - `face_recognition` (dlib-based, CPU-optimized)
  - `insightface` (deep learning, more accurate)
- **Google Photos Integration**: Automatic upload with OAuth authentication
- **Deduplication**: SHA256-based tracking prevents reprocessing
- **Thread-Safe**: Handles concurrent file operations safely
- **Retry Logic**: Automatic exponential backoff for network errors

## Installation

```bash
# Clone the repository
cd wa_automate

# Install with all face recognition backends
pip install -e ".[all]"

# Or install with specific backend
pip install -e ".[face-recognition]"  # dlib/face_recognition
pip install -e ".[insightface]"       # InsightFace
```

## Configuration

1. Copy the example configuration:
```bash
cp config.example.yaml config.yaml
```

2. Edit `config.yaml`:
   - Set `watch_dirs` to your WhatsApp media directories
   - Configure `known_people_dir` with reference face images
   - Adjust recognition settings (backend, tolerance)
   - Optionally set `google_photos_album_name`

3. Set up Google Photos API:
   - Create a project in Google Cloud Console
   - Enable Google Photos Library API
   - Download `client_secret.json` to the repository root directory

## Known People Directory Structure

Organize your reference face images in the `data/known_people/` directory:

```
data/known_people/
  person1/
    photo1.jpg
    photo2.jpg
  person2/
    photo1.jpg
```

See `data/known_people/README.md` for detailed instructions on providing reference images.

## Usage

```bash
# Run with default config.yaml in current directory
python -m wa_automate

# Or specify a config file
python -m wa_automate --config /path/to/config.yaml

# Or use the CLI command (after installation)
wa-automate --config config.yaml
```

## Development Status

**Phase A (Complete)**: Critical bug fixes
- ✅ Factory pattern for backend selection
- ✅ RGB/BGR color bug fix
- ✅ InsightFace model caching
- ✅ Thread-safe database
- ✅ API retry logic

**Phase B (Complete)**: Project restructuring
- ✅ Professional `src/` layout
- ✅ Pydantic configuration validation
- ✅ Modern `pyproject.toml` packaging
- ✅ Entry point with argparse

**Future Phases**: Unit tests, CI/CD, cloud deployment

## License

MIT
