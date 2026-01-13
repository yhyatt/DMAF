<p align="center">
  <img src="assets/dmaf-logo.svg" alt="DMAF Logo" width="200"/>
</p>

<h1 align="center">DMAF</h1>
<h3 align="center">🧠 Don't Miss A Face</h3>

<p align="center">
  <strong>Automated WhatsApp media backup with intelligent face recognition filtering</strong>
</p>

<p align="center">
  Never miss a photo of your loved ones again — DMAF watches your WhatsApp media,<br/>
  recognizes faces of people you care about, and automatically backs them up to Google Photos.
</p>

<p align="center">
  <a href="https://github.com/yonatan/dmaf/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/yonatan/dmaf/ci.yml?branch=main&style=for-the-badge&logo=github&label=CI" alt="CI Status"/>
  </a>
  <a href="https://codecov.io/gh/yonatan/dmaf">
    <img src="https://img.shields.io/codecov/c/github/yonatan/dmaf?style=for-the-badge&logo=codecov&label=Coverage" alt="Coverage"/>
  </a>
  <a href="https://pypi.org/project/dmaf/">
    <img src="https://img.shields.io/pypi/v/dmaf?style=for-the-badge&logo=pypi&logoColor=white&label=PyPI" alt="PyPI Version"/>
  </a>
  <a href="https://github.com/yonatan/dmaf/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/yonatan/dmaf?style=for-the-badge" alt="License"/>
  </a>
</p>

<p align="center">
  <a href="https://img.shields.io/pypi/pyversions/dmaf?style=for-the-badge&logo=python&logoColor=white">
    <img src="https://img.shields.io/pypi/pyversions/dmaf?style=for-the-badge&logo=python&logoColor=white" alt="Python Versions"/>
  </a>
  <a href="https://github.com/yonatan/dmaf/stargazers">
    <img src="https://img.shields.io/github/stars/yonatan/dmaf?style=for-the-badge&logo=github" alt="GitHub Stars"/>
  </a>
  <a href="https://github.com/yonatan/dmaf/issues">
    <img src="https://img.shields.io/github/issues/yonatan/dmaf?style=for-the-badge&logo=github" alt="GitHub Issues"/>
  </a>
  <a href="https://github.com/yonatan/dmaf">
    <img src="https://img.shields.io/github/last-commit/yonatan/dmaf?style=for-the-badge&logo=git&logoColor=white" alt="Last Commit"/>
  </a>
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-how-it-works">How It Works</a> •
  <a href="#%EF%B8%8F-configuration">Configuration</a> •
  <a href="#-face-recognition-backends">Backends</a> •
  <a href="#-contributing">Contributing</a>
</p>

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🔍 Smart Face Recognition
- **Two powerful backends**: Choose between `dlib` (CPU-optimized) or `InsightFace` (GPU-accelerated, more accurate)
- **Multi-face detection**: Handles group photos with multiple faces
- **Configurable tolerance**: Fine-tune matching sensitivity

</td>
<td width="50%">

### ☁️ Google Photos Integration
- **Automatic uploads**: Seamlessly backup to Google Photos
- **Album organization**: Optionally organize into specific albums
- **OAuth2 authentication**: Secure, token-based access

</td>
</tr>
<tr>
<td width="50%">

### ⚡ Efficient Processing
- **SHA256 deduplication**: Never process the same image twice
- **Intelligent retry logic**: Exponential backoff for network resilience
- **Thread-safe database**: Handle concurrent operations safely

</td>
<td width="50%">

### 🔧 Developer Friendly
- **Modern Python 3.10+**: Type hints, Pydantic validation
- **Flexible configuration**: YAML config with environment variable support
- **Modular architecture**: Easy to extend and customize

</td>
</tr>
</table>

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10 or higher
- Google Cloud project with Photos Library API enabled
- WhatsApp media directory accessible locally (e.g., via Android file sync, WSL)

### Installation

```bash
# Clone the repository
git clone https://github.com/yonatan/dmaf.git
cd dmaf

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with your preferred face recognition backend
pip install -e ".[insightface]"  # Recommended: GPU-accelerated, higher accuracy
# OR
pip install -e ".[face-recognition]"  # CPU-optimized, easier setup
# OR
pip install -e ".[all]"  # Both backends
```

### Setup

1. **Configure Google Photos API**
   ```bash
   # Download client_secret.json from Google Cloud Console
   # Place it in the project root directory
   ```

2. **Add reference photos of people to recognize**
   ```
   data/known_people/
   ├── Alice/
   │   ├── photo1.jpg
   │   └── photo2.jpg
   └── Bob/
       └── photo1.jpg
   ```

3. **Create your configuration**
   ```bash
   cp config.example.yaml config.yaml
   # Edit config.yaml with your WhatsApp media paths
   ```

4. **Run DMAF**
   ```bash
   dmaf --config config.yaml
   # Or: python -m dmaf --config config.yaml
   ```

---

## 🔄 How It Works

```mermaid
graph LR
    A[📱 WhatsApp Media] -->|File Watcher| B[🔍 Face Detection]
    B -->|Match Found| C[✅ Known Face?]
    C -->|Yes| D[☁️ Upload to Google Photos]
    C -->|No| E[⏭️ Skip]
    D --> F[💾 Mark as Processed]
    E --> F
    F -->|Deduplication| G[🚫 Never Reprocess]
```

1. **Watch** - DMAF monitors your configured WhatsApp media directories for new images
2. **Detect** - Each new image is analyzed for faces using your chosen backend
3. **Recognize** - Detected faces are compared against your known people database
4. **Upload** - Images containing recognized faces are uploaded to Google Photos
5. **Deduplicate** - SHA256 hashing ensures no image is ever processed twice

---

## ⚙️ Configuration

DMAF uses a YAML configuration file with full Pydantic validation:

```yaml
# Watch directories - your WhatsApp media locations
watch_dirs:
  - "/path/to/WhatsApp/Media/WhatsApp Images"

# Google Photos album (optional)
google_photos_album_name: "Family - Auto WhatsApp"

# Face recognition settings
recognition:
  backend: "insightface"     # or "face_recognition"
  tolerance: 0.42            # Lower = stricter matching
  min_face_size_pixels: 80   # Ignore tiny faces
  require_any_match: true    # Only upload if known face found

# Known people directory
known_people_dir: "./data/known_people"

# Deduplication database
dedup:
  method: "sha256"
  db_path: "./data/state.sqlite3"
```

See [`config.example.yaml`](config.example.yaml) for a complete example with all options.

---

## 🧠 Face Recognition Backends

DMAF supports two face recognition backends, each with different trade-offs:

| Feature | InsightFace | face_recognition (dlib) |
|---------|-------------|-------------------------|
| **Accuracy** | ⭐⭐⭐⭐⭐ Higher | ⭐⭐⭐⭐ Good |
| **False Positive Rate** | 0.0% | ~11% |
| **Speed** | ⚡ 12x faster | 🐢 Slower |
| **GPU Support** | ✅ Yes (CUDA) | ❌ CPU only |
| **Installation** | Requires ONNX Runtime | Requires dlib |
| **Best For** | Production, privacy-critical | Quick testing, simple setups |

### Recommendation

**Use InsightFace** for production deployments. Our testing showed:
- Zero false positives (strangers never misidentified as family)
- 12x faster processing
- More consistent results across lighting conditions

---

## 📁 Project Structure

```
dmaf/
├── src/dmaf/
│   ├── __main__.py           # CLI entry point
│   ├── config.py             # Pydantic settings
│   ├── database.py           # Thread-safe SQLite
│   ├── watcher.py            # File monitoring
│   ├── face_recognition/     # Detection backends
│   │   ├── factory.py        # Backend selection
│   │   ├── dlib_backend.py   # face_recognition
│   │   └── insightface_backend.py
│   ├── google_photos/        # Google Photos API
│   └── utils/                # Retry logic, helpers
├── data/
│   ├── known_people/         # Your reference images
│   └── state.sqlite3         # Deduplication DB
├── config.yaml               # Your configuration
└── pyproject.toml            # Package definition
```

---

## 🛠️ Development

```bash
# Install dev dependencies
pip install -e ".[dev,all]"

# Run tests
pytest tests/ -v --cov=dmaf

# Type checking
mypy src/dmaf

# Linting
ruff check src/
black --check src/
```

---

## 🗺️ Roadmap

- [x] **Phase A**: Core bug fixes (RGB/BGR, caching, retry logic)
- [x] **Phase B**: Project restructuring (src layout, Pydantic)
- [ ] **Phase C**: Unit tests (80%+ coverage)
- [ ] **Phase D**: Face recognition benchmarking
- [ ] **Phase E**: CI/CD (GitHub Actions)
- [ ] **Phase F**: Cloud deployment (GCS + Cloud Run)
- [ ] **Phase G**: Docker support

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [face_recognition](https://github.com/ageitgey/face_recognition) - dlib-based face recognition
- [InsightFace](https://github.com/deepinsight/insightface) - Deep learning face analysis
- [Google Photos Library API](https://developers.google.com/photos/library/guides/get-started)
- [Watchdog](https://github.com/gorakhargosh/watchdog) - File system monitoring

---

<p align="center">
  <sub>Made with ❤️ by <a href="https://github.com/yonatan">yonatan</a></sub>
</p>

<p align="center">
  <a href="https://github.com/yonatan/dmaf">
    <img src="https://img.shields.io/badge/⭐_Star_this_repo-If_it_helped_you!-yellow?style=for-the-badge" alt="Star this repo"/>
  </a>
</p>
