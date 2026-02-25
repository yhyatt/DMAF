# DMAF + OpenClaw Integration Guide

Automatically capture WhatsApp group photos and feed them into the DMAF pipeline using [OpenClaw](https://openclaw.ai) as the WhatsApp media interceptor.

**This is the recommended approach for iPhone users** — no WhatsApp Desktop, no rclone, no desktop machine required.

---

## Architecture Overview

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ WhatsApp Groups  │ ──> │ OpenClaw Gateway  │ ──> │ GCS Bucket       │ ──> │ Cloud Run Job   │
│ (group messages) │     │ (Baileys client)  │     │ (staging area)   │     │ (DMAF scanner)  │
└──────────────────┘     └──────────────────┘     └──────────────────┘     └─────────────────┘
                          media/inbound/            gsutil sync              face recognition
                          auto-download             every 30 min            ↓
                                                                       ┌─────────────────┐
                                                                       │ Google Photos   │
                                                                       │ (matched faces) │
                                                                       └─────────────────┘
```

**Key Advantages**:
- ✅ Works with iPhone (no Android-only sync tools needed)
- ✅ No WhatsApp Desktop required
- ✅ Captures media from ALL your WhatsApp groups automatically
- ✅ Silent — doesn't respond in groups unless mentioned
- ✅ Zero changes to the DMAF Cloud Run pipeline
- ✅ Runs on the same machine as OpenClaw (WSL, Linux, macOS)

**Limitations**:
- ⚠️ Only captures media from **other people** in groups (your own sent photos are filtered by self-chat protection)
- ⚠️ Uses Baileys (unofficial WhatsApp Web client) — see [Ban Risk](#ban-risk-considerations) section
- ⚠️ Requires OpenClaw to be running continuously

---

## Prerequisites

- **OpenClaw** installed and running with WhatsApp channel linked
- **GCP project** with DMAF Cloud Run job deployed (see [main deployment guide](README.md))
- **gcloud CLI** authenticated on the OpenClaw host machine

---

## Step 1: Configure OpenClaw for Group Media Collection

OpenClaw needs to accept group messages (for media download) without responding to them.

In `~/.openclaw/openclaw.json`, configure WhatsApp groups:

```json5
{
  channels: {
    whatsapp: {
      groupPolicy: "allowlist",
      groups: {
        "*": { requireMention: true }  // Accept all groups, only respond when @mentioned
      },
      groupAllowFrom: ["*"],           // Accept messages from all group members
      mediaMaxMb: 50                   // Max media file size to download
    }
  }
}
```

**How it works**:
- `groups: { "*": ... }` — all groups are accepted (media gets downloaded)
- `requireMention: true` — OpenClaw stays silent unless explicitly @mentioned
- Media from accepted messages is automatically saved to `~/.openclaw/media/inbound/`

**Security note**: If you only want specific groups, replace `"*"` with group JIDs:
```json5
groups: {
  "120363XXXXX@g.us": { requireMention: true },
  "972XXXXXXXX-XXXXXXXXXX@g.us": { requireMention: true }
}
```

Restart the gateway after config changes:
```bash
openclaw gateway restart
```

### Verify Media Collection

1. Ask someone to send a photo in one of your WhatsApp groups
2. Check if it appears:
```bash
ls -la ~/.openclaw/media/inbound/
```

**Note**: Your own sent photos will NOT appear — OpenClaw's self-chat protection filters messages from the linked WhatsApp number. This is actually ideal for DMAF: photos you took are already on your phone.

---

## Step 2: Authenticate gcloud on OpenClaw Host

The sync script needs `gsutil` access to upload to GCS.

```bash
# If running OpenClaw as a separate user (e.g., 'openclaw'):
sudo -u openclaw gcloud auth login --no-launch-browser

# Follow the browser auth flow and paste the verification code

# Set the project
sudo -u openclaw gcloud config set project dmaf-production
```

Verify access:
```bash
gsutil ls gs://dmaf-production-whatsapp-media/
```

---

## Step 3: Create the Sync Script

Create `~/.openclaw/workspace/scripts/dmaf-sync.sh`:

```bash
#!/bin/bash
# DMAF Media Sync — uploads new WhatsApp images to GCS staging bucket
# Deletes local files after successful upload to prevent disk bloat

INBOUND_DIR="$HOME/.openclaw/media/inbound"
GCS_BUCKET="gs://dmaf-production-whatsapp-media"  # Change to your bucket
SYNCED=0
FAILED=0

for f in "$INBOUND_DIR"/*.{jpg,jpeg,png}; do
    [ -f "$f" ] || continue
    basename=$(basename "$f")

    if gsutil -q cp "$f" "$GCS_BUCKET/$basename" 2>/dev/null; then
        rm "$f"
        SYNCED=$((SYNCED + 1))
    else
        FAILED=$((FAILED + 1))
        echo "Failed: $basename" >&2
    fi
done

if [ $SYNCED -gt 0 ] || [ $FAILED -gt 0 ]; then
    echo "Synced: $SYNCED | Failed: $FAILED"
else
    echo "No new images"
fi
```

```bash
chmod +x ~/.openclaw/workspace/scripts/dmaf-sync.sh
```

**Notes**:
- Only syncs image files (JPG, JPEG, PNG) — skips videos and other media
- Deletes local files after successful upload to prevent disk bloat
- Failed uploads are retried on next run (file stays in place)

---

## Step 4: Schedule the Sync

### Option A: OpenClaw Cron (Recommended)

```bash
openclaw cron add \
  --name "dmaf:media-sync" \
  --cron "*/30 * * * *" \
  --message "Run ~/.openclaw/workspace/scripts/dmaf-sync.sh and report how many new images were synced. If zero, reply HEARTBEAT_OK." \
  --agent main
```

### Option B: System Crontab

```bash
crontab -e
# Add:
*/30 * * * * /home/openclaw/.openclaw/workspace/scripts/dmaf-sync.sh >> /tmp/dmaf-sync.log 2>&1
```

---

## Step 5: Verify Cloud Run IAM Permissions

The Cloud Scheduler service account needs permission to invoke the Cloud Run job. This is a common issue after initial deployment.

**Check if the scheduler is working**:
```bash
gcloud logging read 'resource.type="cloud_scheduler_job"' --limit=5 \
  --format='value(textPayload,jsonPayload)' --freshness=6h
```

If you see `PERMISSION_DENIED` or `403`:

```bash
# Grant the service account permission to invoke the Cloud Run job
gcloud run jobs add-iam-policy-binding dmaf-scan \
  --region=us-central1 \
  --member="serviceAccount:dmaf-runner@dmaf-production.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

**Verify with a manual test run**:
```bash
gcloud run jobs execute dmaf-scan --region=us-central1
```

Monitor execution:
```bash
# Check execution status
gcloud run jobs executions list --job=dmaf-scan --region=us-central1 --limit=3

# View logs
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="dmaf-scan"' \
  --limit=30 --format='value(textPayload)' --freshness=1h
```

---

## End-to-End Verification

1. **Someone sends a photo** in a WhatsApp group
2. **Check media landed** (within seconds):
   ```bash
   ls -la ~/.openclaw/media/inbound/
   ```
3. **Wait for sync** (or run manually):
   ```bash
   bash ~/.openclaw/workspace/scripts/dmaf-sync.sh
   ```
4. **Check GCS**:
   ```bash
   gsutil ls gs://dmaf-production-whatsapp-media/ | tail -5
   ```
5. **Trigger Cloud Run** (or wait for scheduler):
   ```bash
   gcloud run jobs execute dmaf-scan --region=us-central1
   ```
6. **Check logs for face matches**:
   ```bash
   gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="dmaf-scan"' \
     --limit=30 --format='value(textPayload)' --freshness=1h
   ```
7. **Check Google Photos** for the uploaded image

---

## Ban Risk Considerations

OpenClaw uses **Baileys**, an unofficial WhatsApp Web reverse-engineering library. This is a **Terms of Service violation** and carries a risk of account ban.

**Risk mitigation**:
- Use `requireMention: true` — OpenClaw stays silent in groups (passive listener)
- Don't send automated messages to groups
- Frequent disconnects (408/428 status codes) may indicate WhatsApp detection
- Consider using a **separate WhatsApp number** for OpenClaw if available
- The official WhatsApp Business API does NOT support group participation or general-purpose AI assistants (as of Jan 2026)

**If banned**: Your WhatsApp number is temporarily or permanently restricted. Use a disposable prepaid SIM for OpenClaw if you want zero risk to your primary number.

---

## Troubleshooting

### No media files appearing in `media/inbound/`

1. Check OpenClaw gateway is running: `openclaw gateway status`
2. Check WhatsApp is connected: `openclaw channels status`
3. Verify group config in `openclaw.json` — `groupPolicy` must be `"allowlist"` and `groups` must include the target groups
4. **Your own messages are filtered** — have someone else send a photo
5. Check gateway logs: `openclaw logs -n 50`

### Sync script uploads nothing

1. Check gcloud auth: `gcloud auth list`
2. Check bucket access: `gsutil ls gs://your-bucket/`
3. Check file permissions on `media/inbound/`
4. Run script manually with verbose output to see errors

### Cloud Run job not processing images

1. Check scheduler permissions (see Step 5 above)
2. Check execution status: `gcloud run jobs executions list --job=dmaf-scan --region=us-central1 --limit=3`
3. Check for Firestore index warnings in logs (non-critical, see [main deployment guide](README.md#firestore-index-warnings-non-critical))
4. Verify GCS bucket has images: `gsutil ls gs://your-bucket/`

### WhatsApp frequent disconnects

Status codes 408 (timeout), 428 (rate limit), 499 (client disconnect) are common with Baileys. OpenClaw auto-reconnects. If disconnects increase significantly, reduce group activity or consider a separate number.
