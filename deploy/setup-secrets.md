# DMAF — Secrets & Credentials Setup

Complete guide to setting up every credential DMAF needs.
Do this once for a new deployment. Takes about 30 minutes.

> **Coding agents**: This is the authoritative reference for what secrets exist,
> where they live, and what IAM roles are required. When you see a 403 or a
> "credential not found" error, check here first.

---

## Overview of What You'll Create

| Credential | Where It Lives | Used By |
|------------|---------------|---------|
| GCP Service Account (`dmaf-runner`) | GCP IAM | Cloud Run job |
| GCS bucket: media staging | GCS | OpenClaw sync → DMAF scanner |
| GCS bucket: known people | GCS | Container startup (reference photos) |
| Google Photos OAuth token | Secret Manager (`dmaf-photos-token`) | DMAF uploader |
| DMAF config YAML | Secret Manager (`dmaf-config`) | Cloud Run job |
| Gmail App Password (optional) | Inside `dmaf-config` | Alert emails |

---

## Step 1: GCP Project

```bash
# Create a new project (or use existing)
gcloud projects create dmaf-production --name="DMAF"
gcloud config set project dmaf-production

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com
```

### Firestore database

```bash
gcloud firestore databases create --location=us-central1
```

---

## Step 2: Service Account

```bash
# Create
gcloud iam service-accounts create dmaf-runner \
  --display-name="DMAF Cloud Run runner"

SA="dmaf-runner@dmaf-production.iam.gserviceaccount.com"

# Required roles
gcloud projects add-iam-policy-binding dmaf-production \
  --member="serviceAccount:$SA" --role="roles/datastore.user"          # Firestore

gcloud projects add-iam-policy-binding dmaf-production \
  --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"  # Secret Manager

gcloud projects add-iam-policy-binding dmaf-production \
  --member="serviceAccount:$SA" --role="roles/storage.objectAdmin"     # GCS read/write

# Allow the SA to invoke itself (needed for Cloud Scheduler → Cloud Run)
gcloud run jobs add-iam-policy-binding dmaf-scan \
  --region=us-central1 \
  --member="serviceAccount:$SA" \
  --role="roles/run.invoker"
# Note: run this AFTER the Cloud Run job is created (Step 6)
```

---

## Step 3: GCS Buckets

```bash
PROJECT=dmaf-production
REGION=us-central1

# Staging bucket: WhatsApp media waiting to be scanned
gsutil mb -p $PROJECT -l $REGION gs://${PROJECT}-whatsapp-media/

# Known people bucket: reference photos for face recognition
gsutil mb -p $PROJECT -l $REGION gs://${PROJECT}-known-people/

# Grant service account access to both buckets
gsutil iam ch serviceAccount:dmaf-runner@${PROJECT}.iam.gserviceaccount.com:objectAdmin \
  gs://${PROJECT}-whatsapp-media/

gsutil iam ch serviceAccount:dmaf-runner@${PROJECT}.iam.gserviceaccount.com:objectViewer \
  gs://${PROJECT}-known-people/
```

### Upload your reference photos

One sub-directory per person, named exactly as you want them matched:

```
data/known_people/
├── alice/
│   ├── alice_001.jpg
│   └── alice_002.jpg
└── bob/
    └── bob_001.jpg
```

```bash
gsutil -m rsync -r -x ".*Zone\.Identifier$" \
  data/known_people/ gs://${PROJECT}-known-people/
```

---

## Step 4: Google Photos OAuth Token

This is the most involved step. DMAF needs offline access to upload to your Google Photos.

### 4a. Create OAuth credentials

1. Go to [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. Enable **Photos Library API** for your project
3. Create **OAuth 2.0 Client ID** → Application type: **Desktop app** → name: `DMAF`
4. Download the JSON → save as `client_secret.json` in the repo root

### 4b. Authorize and get the token

```bash
# Install dmaf locally first
pip install -e ".[insightface]"

# Run the auth flow — opens browser
python -c "
from dmaf.google_photos.auth import get_creds
creds = get_creds()
print('Token saved to token.json')
"
```

This creates `token.json` in the current directory.

### 4c. Upload token to Secret Manager

```bash
# Create the secret (first time)
gcloud secrets create dmaf-photos-token --project=dmaf-production

# Upload the token
gcloud secrets versions add dmaf-photos-token \
  --data-file=token.json \
  --project=dmaf-production

# The DMAF config references this secret — see Step 5
```

> **Token expiry**: Google refresh tokens don't expire unless you revoke them or go
> 6 months without use. If the pipeline stops uploading, re-run step 4b and push a
> new secret version.

---

## Step 5: DMAF Config in Secret Manager

Create your `config.yaml` using the annotated template:

```yaml
# ── Watch source ───────────────────────────────────────────────────────────
watch_dirs:
  - "gs://dmaf-production-whatsapp-media/"   # Your staging bucket

# ── Known people ───────────────────────────────────────────────────────────
known_people_gcs_uri: "gs://dmaf-production-known-people"
  # DMAF downloads these at container startup. One subdir per person.

# ── Face recognition ───────────────────────────────────────────────────────
recognition:
  backend: insightface          # insightface | face_recognition | auraface
  tolerance: 0.5                # Match threshold (0-1). Lower = stricter.
  min_face_size_pixels: 20
  det_thresh: 0.5               # Detection confidence threshold
  det_thresh_known: 0.3         # Lower threshold for known-people training pass
  return_best_only: true

# ── Google Photos ───────────────────────────────────────────────────────────
google_photos_token_secret: "dmaf-photos-token"  # Secret Manager secret name
google_photos_album_name: "DMAF Auto-Import"     # Leave empty to skip album

# ── Deduplication ──────────────────────────────────────────────────────────
dedup:
  backend: firestore            # firestore (cloud) | sqlite (local dev)
  firestore_project: dmaf-production
  firestore_collection: dmaf_files

# ── Alerting (optional) ────────────────────────────────────────────────────
alerting:
  enabled: true                 # Set false to disable email alerts
  recipients:
    - "you@example.com"
  batch_interval_minutes: 60
  borderline_offset: 0.1
  event_retention_days: 90
  timezone: "America/New_York"  # IANA timezone name for alert email timestamps
  smtp:
    host: "smtp.gmail.com"
    port: 587
    username: "dmaf.alerts@gmail.com"
    password: "xxxx xxxx xxxx xxxx"   # Gmail App Password (see Step 5a)
    use_tls: true
    sender_email: "dmaf.alerts@gmail.com"

# ── Misc ───────────────────────────────────────────────────────────────────
delete_source_after_upload: false  # Set true to delete GCS object after upload
```

```bash
# Create secret (first time)
gcloud secrets create dmaf-config --project=dmaf-production

# Push config
gcloud secrets versions add dmaf-config \
  --data-file=config.yaml \
  --project=dmaf-production

# To update later:
gcloud secrets versions add dmaf-config --data-file=config.yaml
```

### 5a. Gmail App Password (for alerting)

1. Enable 2FA on the Gmail account you want to send from
2. Go to [Google Account → Security → App passwords](https://myaccount.google.com/apppasswords)
3. Create a new app password → name: `DMAF`
4. Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`) into `smtp.password`

---

## Step 6: Cloud Build + Cloud Run

```bash
# Build the Docker image and push to GCR
gcloud builds submit --config cloudbuild.yaml

# Create the Cloud Run job (uses the image just built)
gcloud run jobs create dmaf-scan \
  --image=gcr.io/dmaf-production/dmaf:latest \
  --region=us-central1 \
  --service-account=dmaf-runner@dmaf-production.iam.gserviceaccount.com \
  --set-secrets="/run/secrets/dmaf-config=dmaf-config:latest,/run/secrets/dmaf-photos-token=dmaf-photos-token:latest" \
  --memory=2Gi \
  --cpu=2 \
  --max-retries=0 \
  --task-timeout=20m

# Now grant the scheduler permission to invoke it (see Step 2)
gcloud run jobs add-iam-policy-binding dmaf-scan \
  --region=us-central1 \
  --member="serviceAccount:dmaf-runner@dmaf-production.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

---

## Step 7: Cloud Scheduler (Hourly Trigger)

```bash
gcloud scheduler jobs create http dmaf-schedule \
  --location=us-central1 \
  --schedule="0 * * * *" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/dmaf-production/jobs/dmaf-scan:run" \
  --message-body='{}' \
  --oauth-service-account-email="dmaf-runner@dmaf-production.iam.gserviceaccount.com" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
```

---

## Step 8: Firestore Indexes

DMAF queries Firestore with compound filters. Create the required indexes:

```bash
gcloud firestore indexes composite create \
  --collection-group=error_events \
  --field-config field-path=alerted,order=ASCENDING \
  --field-config field-path=created_ts,order=ASCENDING

gcloud firestore indexes composite create \
  --collection-group=borderline_events \
  --field-config field-path=alerted,order=ASCENDING \
  --field-config field-path=created_ts,order=ASCENDING
```

---

## Verification Checklist

```bash
# 1. Service account exists and has roles
gcloud iam service-accounts list --filter="email:dmaf-runner"
gcloud projects get-iam-policy dmaf-production --flatten="bindings[].members" \
  --filter="bindings.members:dmaf-runner"

# 2. Secrets exist
gcloud secrets list --project=dmaf-production
gcloud secrets versions list dmaf-config --project=dmaf-production
gcloud secrets versions list dmaf-photos-token --project=dmaf-production

# 3. GCS buckets accessible
gsutil ls gs://dmaf-production-whatsapp-media/
gsutil ls gs://dmaf-production-known-people/

# 4. Cloud Run job exists
gcloud run jobs describe dmaf-scan --region=us-central1

# 5. Cloud Scheduler job exists
gcloud scheduler jobs list --location=us-central1

# 6. Manual test run
gcloud run jobs execute dmaf-scan --region=us-central1 --async
# Then check logs:
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="dmaf-scan"' \
  --limit=30 --format='value(textPayload)' --freshness=10m
```

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `403 PERMISSION_DENIED` on Cloud Scheduler | Scheduler SA can't invoke job | Re-run the `add-iam-policy-binding` command in Step 2 |
| `404 No document to update` | Old code using `update()` | Should not happen in current code (`set+merge` is used). Check deployed image version. |
| `known_people/` empty in container | GCS bucket not set / wrong URI | Set `known_people_gcs_uri` in config, verify with `gsutil ls` |
| Google Photos upload fails | Token expired / revoked | Re-run Step 4b and push new secret version |
| No media in inbound dir | OpenClaw group config | See [`openclaw-integration.md`](openclaw-integration.md) |
