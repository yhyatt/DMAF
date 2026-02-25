# DMAF Project Guide

## Project Overview
WhatsApp media backup automation with face recognition filtering. Monitors WhatsApp directories, identifies photos of known people, and uploads matches to Google Photos.

**Current Status**: Phase F complete (cloud deployment working end-to-end), Phase G (documentation) in progress, ~90% overall progress

## Communication Preferences

### Tool & Bash Explanations
**Keep it concise**: One sentence explaining WHY you're calling each bash command or permission-requiring tool.

Example: "Staging all changes including deletions with `git add -A` to commit Phase B as one atomic unit"

## Key Decisions Made

### Data Organization (Phase B)
- **Created `data/` directory**: Clean separation of user content from code
- **Moved from `project/`**: Old `project/known_people/` and `project/state.sqlite3` → `data/`
- **OAuth files in root**: `client_secret.json` and `token.json` at root where app runs
- **Rationale**: Semantic clarity - `data/` for user input/output, `src/` for package code, root for config/secrets

### Package Structure
- **src/ layout**: Prevents accidental imports from dev directory, ensures tests run against installed code
- **Pydantic validation**: Catches config errors at startup with clear messages (e.g., "tolerance must be 0-1")
- **Optional dependencies**: Users can install `[face-recognition]`, `[insightface]`, or `[all]` - keeps installations minimal
- **Python 3.10+**: Modern type hints (`list[Path]` not `List[Path]`)

### Known People Reference Photos
- **Cloud deployment**: Reference photos stored in a private GCS bucket, downloaded at container startup
  - Set `known_people_gcs_uri: "gs://your-bucket"` in `config.cloud.yaml`
  - Upload with: `gsutil -m rsync -r -x ".*Zone\.Identifier$" data/known_people/ gs://your-bucket/`
- **Local development**: Uses `data/known_people/` directory

### `known_people_gcs_uri` Config
- Points to a private GCS bucket containing reference photos (one subdirectory per person)
- DMAF downloads them at container startup before running face recognition
- Service account needs `objectViewer` on the bucket

### WhatsApp Media Sources
- **OpenClaw integration**: WhatsApp media interception via OpenClaw (see `deploy/openclaw-integration.md`)
- **WhatsApp Desktop + rclone**: Traditional cross-platform option
- **Android direct sync**: FolderSync Pro, Syncthing

### Privacy & Gitignore
- **Entire `data/` ignored** except `data/known_people/README.md` (instructions only)
- **Personal photos protected**: known_people/ contains family photos of Lenny, Louise, Zoe, yonatan
- **Never commit**: `client_secret.json`, `token.json`, `config.yaml`, anything in `data/`

## Project Structure

```
wa_automate/                  # Repository/project root
├── src/dmaf/                 # Package source
│   ├── google_photos/        # Google Photos API
│   ├── face_recognition/     # Face backends (factory pattern)
│   └── utils/                # Shared utilities
├── data/                     # User data (gitignored)
│   ├── known_people/         # Reference faces - local dev only (cloud: GCS bucket)
│   └── state.sqlite3         # Deduplication DB (local only; cloud uses Firestore)
├── config.yaml               # Runtime config (gitignored)
└── pyproject.toml            # Package definition
```

## Important Notes

### Privacy & Data
- **NEVER show contents of files in `data/known_people/`** - contains family photos
- `data/` directory is entirely gitignored except `known_people/README.md`
- `client_secret.json` and `token.json` are OAuth credentials - never commit

### Testing & Verification
- Virtual environment: `.venv/bin/python`
- CLI commands: `python -m dmaf` or `dmaf`
- Config: `config.yaml` (paths relative to project root)

### Code Style
- Python 3.10+ type hints (modern syntax: `list[Path]` not `List[Path]`)
- Pydantic for config validation
- Factory pattern for face recognition backends
- Thread-safe database operations

### Automated Linting (Pre-commit Hooks)
- **Installed**: Git hooks auto-format code before each commit
- **Setup**: `pre-commit install` (already done)
- **Manual run**: `pre-commit run --all-files`
- **Hooks**: ruff (linting + formatting), black (formatting), trailing whitespace, etc.
- **Benefit**: Ensures code quality before committing, prevents CI failures

## Development Phases

- ✅ **Phase A**: Critical bug fixes (RGB/BGR, caching, retry logic)
- ✅ **Phase B**: Project restructuring (src/ layout, Pydantic, pyproject.toml)
- ✅ **Phase C**: Unit tests (81% coverage, 129 tests)
- ✅ **Phase D**: Face recognition benchmarking & LOOCV validation
- ✅ **Phase D+**: Advanced detection tuning (separate thresholds, LOOCV bug fix, FPR analysis)
- ✅ **Phase E**: CI/CD (GitHub Actions, automated testing)
- ✅ **Phase F-prep**: Observability & auto-refresh (alerting, score tracking, known refresh)
- ✅ **Phase F**: Cloud deployment (GCS + Cloud Run + Firestore backend)
- 🚧 **Phase G**: Documentation & open-source - IN PROGRESS
- ✅ **Video Processing**: Scan WhatsApp video clips for known faces (`find_face_in_video`), early exit on first match, upload matched videos to Google Photos

## Useful Commands

```bash
# Install package (editable mode)
.venv/bin/pip install -e ".[all,dev]"

# Setup pre-commit hooks (automatic linting before commits)
pre-commit install

# Run application
python -m dmaf --config config.yaml

# Run tests
pytest tests/ -v --cov=dmaf

# Manual linting (pre-commit does this automatically)
ruff check src/ tests/ --fix
black src/ tests/
mypy src/dmaf

# Run all pre-commit hooks manually
pre-commit run --all-files
```

## Cloud Deployment Commands

```bash
# Build and deploy to Cloud Run
gcloud builds submit --config cloudbuild.yaml

# Execute Cloud Run Job manually
gcloud run jobs execute dmaf-scan --region=us-central1

# View recent logs
gcloud logging read "resource.type=cloud_run_job" \
  --limit=50 --format="table(timestamp, textPayload)" --freshness=5m

# Update config secret
gcloud secrets versions add dmaf-config --data-file=config.cloud.yaml

# Check job status
gcloud run jobs describe dmaf-scan --region=us-central1

# List recent executions
gcloud run jobs executions list --job=dmaf-scan --region=us-central1 --limit=10

# Sync known_people reference photos to GCS (no rebuild needed)
gsutil -m rsync -r -x ".*Zone\.Identifier$" data/known_people/ gs://your-bucket/
```

**See full deployment guide**: `deploy/README.md`

## Dependencies
- **Core**: Pydantic, PyYAML, Pillow, NumPy, requests, watchdog
- **Google**: google-auth, google-auth-oauthlib
- **Face Recognition**:
  - Option 1: `face-recognition` (dlib-based, CPU-optimized)
  - Option 2: `insightface` (deep learning, GPU-friendly, more accurate)
  - Install: `pip install -e ".[all]"` for both
