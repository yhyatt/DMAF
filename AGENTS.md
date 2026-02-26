# DMAF — Coding Agent Guide

> For Claude Code, GitHub Copilot, Cursor, and any other AI coding assistant.
> Read this before touching anything. It will save you hours.

---

## What This Is

**DMAF (Don't Miss A Face)** — WhatsApp media → face recognition → Google Photos.

Photos and videos arrive from WhatsApp groups, get staged in a GCS bucket, a Cloud Run job
scans them with face recognition, and matched media (people you care about) gets uploaded to
Google Photos automatically.

---

## Architecture

```
WhatsApp groups
      │  (photos/videos from other group members)
      ▼
OpenClaw Gateway          ← unofficial WhatsApp Web client (Baileys)
  ~/.openclaw/media/inbound/
      │  (system cron, every 30 min, zero LLM cost)
      ▼
GCS staging bucket        ← gs://your-bucket/
  gs://your-project-whatsapp-media/
      │  (Cloud Scheduler, hourly)
      ▼
Cloud Run Job: dmaf-scan  ← Docker image from Cloud Build
      │  scans each file, face recognition against known_people/
      │  two-layer dedup via Firestore (path + content SHA-256)
      ▼
Google Photos             ← matched faces only, organised into named album
```

**Key constraint**: OpenClaw's self-chat protection means your OWN sent photos never reach
the pipeline. Only photos sent by others in groups are captured.

---

## Codebase Map

```
src/dmaf/
├── __main__.py          # CLI entrypoint + Uploader class (on_match / on_match_video)
├── config.py            # Pydantic Settings — all config fields with defaults + docs
├── watcher.py           # Core scan loop: scan_and_process_once, _process_image_file,
│                        #   _process_video_file, NewImageHandler base class
├── video_processor.py   # iter_frames (generator), find_face_in_video (early exit)
├── gcs_watcher.py       # GCS helpers: list_gcs_images, list_gcs_videos,
│                        #   download_gcs_blob, cleanup_temp_file
├── database.py          # SQLiteDatabase (local dev) + FirestoreDatabase (cloud)
│                        #   Both implement: seen, add_file_with_score, mark_uploaded
├── known_refresh.py     # Auto-add high-quality matched frames to known_people
├── alerting/
│   ├── alert_manager.py # AlertManager: batches events, sends email on schedule
│   └── templates.py     # format_error_alert, format_borderline_alert
│                        #   _format_ts(ts, tz_name) — configurable timezone
├── face_recognition/    # Backend factory: dlib, InsightFace, AuraFace
├── google_photos/       # upload_bytes, create_media_item, ensure_album
└── utils/               # retry decorator, sha256_of_file, etc.

deploy/
├── README.md            # Full GCP deployment walkthrough
├── setup-secrets.md     # ALL credentials setup (start here for a new deployment)
└── openclaw-integration.md  # OpenClaw → GCS media sync setup

tests/                   # pytest — mirrors src/dmaf structure
config.cloud.yaml.example  # Annotated config template
cloudbuild.yaml          # Cloud Build: docker build + push to GCR
```

---

## Development Quickstart

```bash
git clone https://github.com/yhyatt/DMAF.git && cd DMAF

# Create virtualenv and install with all deps + dev tools
python -m venv .venv && source .venv/bin/activate
pip install -e ".[insightface,dev]"   # or [face-recognition,dev] for dlib

# Install pre-commit hooks (ruff + mypy run before every commit)
pre-commit install

# Run tests
pytest tests/ -v

# Run linting manually
ruff check src/ tests/
mypy src/dmaf
```

For a new deployment, start with **[`deploy/setup-secrets.md`](deploy/setup-secrets.md)**.

---

## Configuration

All config lives in one YAML file (local dev: `config.yaml`, cloud: Secret Manager
`dmaf-config` latest version). The full schema with defaults and descriptions is in
`src/dmaf/config.py` — read it before guessing field names.

**Cloud deployment**: config is read from Secret Manager at container startup.
To update: `gcloud secrets versions add dmaf-config --data-file=config.yaml`

**Key fields you'll touch most:**
```yaml
watch_dirs:
  - "gs://your-bucket/"          # GCS bucket as watch source

known_people_gcs_uri: "gs://your-known-people-bucket"  # Reference photos

alerting:
  enabled: true
  timezone: "America/New_York"   # IANA name — displayed in alert emails
  recipients: ["you@example.com"]
```

See [`config.cloud.yaml.example`](config.cloud.yaml.example) for a full annotated template.

---

## Testing

```bash
pytest tests/ -v                          # All tests
pytest tests/ -v -k "not slow"            # Skip slow tests (CI default)
pytest tests/test_watcher.py -v           # One module
pytest tests/ --cov=dmaf --cov-report=term-missing  # With coverage
```

**CI runs four jobs** (must all pass before merge):
| Job | What it checks |
|-----|---------------|
| `Lint (ruff)` | `ruff check src/ tests/` — style + import order |
| `Type Check (mypy)` | `mypy src/dmaf` — strict type checking |
| `Test (Python 3.10/3.11/3.12)` | `pytest tests/ -v -k "not slow"` |
| `Test with Face Recognition Backends` | Full install with insightface, runs all tests |

**Mock patterns** (copy from existing tests, don't reinvent):
```python
# Image processing
@patch("dmaf.watcher.Image.open")
@patch("dmaf.watcher.sha256_of_file")

# Video processing — patch at the source module, not the caller
@patch("dmaf.video_processor.find_face_in_video")

# GCS
@patch("dmaf.gcs_watcher._get_storage_client")

# Batch scan — use scan_and_process_once directly with a temp dir
from dmaf.watcher import scan_and_process_once
result = scan_and_process_once([str(watch_dir)], handler)
assert result.matched == 1
```

**Fixtures** live in `tests/conftest.py`:
- `temp_dir` — temporary directory, auto-cleaned
- `sample_config_yaml` — minimal valid config YAML written to a temp file

**cv2/insightface tests**: wrap with `pytest.importorskip("cv2")` at module level
so they skip gracefully in the basic CI environment.

---

## Common Pitfalls

**1. Dedup key = GCS URI, not temp path**
When a GCS file is downloaded to `/tmp/dmaf_gcs_xxxx.jpg`, the dedup key must be the
original `gs://bucket/file.jpg`, not the local path. Firestore docs are keyed by
`sha256(gcs_uri)[:32]`. Using the temp path creates a separate doc → mark_uploaded 404.

**1b. Two-layer dedup: path first, then content**
`seen(path)` is checked before downloading (cheap). After downloading, `seen_by_sha256(hash)`
catches the same photo arriving via two different GCS paths (e.g. forwarded across groups).
Both `Database` (SQLite) and `FirestoreDatabase` implement `seen_by_sha256`. The content
check happens in `_process_image_file` and `_process_video_file` before face recognition runs.
Note: WA strips all EXIF on iOS — content SHA-256 works because WA compresses once and the
same compressed bytes are served to all recipients.

**2. `mark_uploaded()` uses `set(merge=True)`, not `update()`**
`update()` raises 404 if the doc doesn't exist. `set(merge=True)` is idempotent.
This was a real bug — don't revert it.

**3. `inspect.signature` for backward-compat `on_match` / `on_match_video`**
`_process_image_file` and `_process_video_file` check whether the handler's `on_match`
accepts `dedup_key` before passing it. This allows subclasses with old signatures to
continue working. Don't remove this pattern without bumping a major version.

**4. `np` in type annotations needs `TYPE_CHECKING`**
`video_processor.py` imports numpy lazily (cv2/numpy are optional heavy deps).
Type annotations use `np.ndarray` but this only works with `from __future__ import annotations`
+ `if TYPE_CHECKING: import numpy as np`. Ruff F821 and mypy both catch violations.

**5. ruff rules you'll hit**
- `E501` — line too long (100 chars). Add `# noqa: E501` for test lines that can't be split.
- `SIM115` — use context manager for `open()` and `NamedTemporaryFile`
- `SIM117` — combine nested `with` statements into one
- `I001` — import block sorting (isort rules): stdlib → third-party → local, then alphabetical
- `F821` — undefined name (usually `np` without TYPE_CHECKING guard)
- `E731` — don't assign a lambda, use a `def`

**6. Firestore `error_events` vs `dmaf_files`**
`error_events` is a separate Firestore collection. Clearing `dmaf_files` (for a fresh scan)
does NOT clear error history. Stale error events will be re-sent by the alert manager if
they still have `alerted=0`.

---

## Cloud Deployment

```bash
# Build and push Docker image (triggers automatically on push via Cloud Build trigger)
gcloud builds submit --config cloudbuild.yaml

# Run the scan job manually
gcloud run jobs execute dmaf-scan --region=us-central1 --async

# Tail logs from most recent execution
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="dmaf-scan"' \
  --limit=50 --format='value(textPayload)' --freshness=30m

# Update the config secret
gcloud secrets versions add dmaf-config --data-file=config.yaml

# Sync known_people reference photos (no Docker rebuild needed)
gsutil -m rsync -r -x ".*Zone\.Identifier$" \
  data/known_people/ gs://your-known-people-bucket/
```

Full GCP setup walkthrough: **[`deploy/setup-secrets.md`](deploy/setup-secrets.md)**

---

## OpenClaw Integration

DMAF supports OpenClaw as a WhatsApp media source. See
**[`deploy/openclaw-integration.md`](deploy/openclaw-integration.md)** for the full
setup guide.

**TL;DR**: OpenClaw auto-downloads WhatsApp group media → a system cron script uploads it
to GCS every 30 min → Cloud Run scans hourly. No LLM tokens involved in the sync.

## MCP Server

`src/dmaf/mcp_server.py` exposes DMAF as MCP tools for Claude Desktop, Claude Code,
Cursor, and any other MCP client. It is a **control plane only** — the pipeline stays
token-free. Tools: `trigger_scan`, `get_status`, `get_logs`, `sync_now`, `list_people`,
`add_person`, `remove_person`, `get_config`, `update_config`.

Setup: **[`deploy/mcp-setup.md`](deploy/mcp-setup.md)**

```bash
pip install -e ".[mcp]"
DMAF_PROJECT=your-project dmaf-mcp   # stdio transport
```

Tests live in `tests/test_mcp_server.py` — all tools mocked via `patch("subprocess.run")`.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| GCS as first-class watch source | Pipeline is cloud-native; local dir support for dev only |
| Firestore for dedup (cloud) | Survives container restarts; no SQLite in Cloud Run |
| Two-layer dedup (path + SHA-256) | Path dedup is O(1) and catches restarts; content SHA-256 catches the same photo forwarded across multiple WA groups (same WA compression = same bytes) |
| `google_photos_album_name` recommended | Native iOS backup + DMAF would both upload the same photo (WA strips EXIF so bytes differ); named album keeps DMAF uploads visually separated |
| Cloud Run Job, not Service | Batch workload — runs, exits, scales to zero |
| `set(merge=True)` for `mark_uploaded` | `update()` raises 404 on missing doc; `set+merge` is idempotent |
| `iter_frames` generator + early exit | Large videos; stop decoding after first match |
| `alerting.timezone` in config | Public repo — never hardcode a timezone |
| System crontab for GCS sync | `agentTurn` cron burns LLM tokens; shell script doesn't |
