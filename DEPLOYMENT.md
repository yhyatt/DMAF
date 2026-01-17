# DMAF Deployment Guide

Complete setup guide for deploying DMAF (Don't Miss A Face) with all features enabled.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Google Photos API Setup](#google-photos-api-setup)
- [Email Alerts Setup (Optional)](#email-alerts-setup-optional)
- [Configuration](#configuration)
- [Running DMAF](#running-dmaf)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required
- **Python 3.10+** - Check with `python --version`
- **Google Cloud Project** with Photos Library API enabled
- **WhatsApp media directory** accessible locally (via Android file sync, WSL, or similar)

### Optional (for Email Alerts)
- **Gmail account** (or other SMTP server)
- **Google App Password** for Gmail SMTP access

---

## Installation

### 1. Clone Repository
```bash
git clone https://github.com/yhyatt/DMAF.git
cd DMAF
```

### 2. Create Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

Choose your preferred face recognition backend:

**Option A: InsightFace (Recommended)**
```bash
pip install -e ".[insightface]"
```
- ✅ 0.0% false positive rate (perfect privacy)
- ✅ 12x faster than dlib
- ✅ GPU-accelerated (CUDA support)
- ⚠️ Requires ONNX Runtime

**Option B: face_recognition (dlib)**
```bash
pip install -e ".[face-recognition]"
```
- ✅ Easy installation
- ✅ CPU-optimized
- ⚠️ ~11% false positive rate
- ⚠️ Requires cmake + dlib

**Option C: Both backends**
```bash
pip install -e ".[all]"
```

### 4. Install Development Tools (Optional)
```bash
pip install -e ".[dev]"
pre-commit install  # Enables auto-formatting before commits
```

---

## Google Photos API Setup

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project (or select existing)
3. Enable **Google Photos Library API**:
   - Navigate to "APIs & Services" → "Library"
   - Search for "Photos Library API"
   - Click "Enable"

### 2. Create OAuth Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. Configure OAuth consent screen:
   - User Type: External
   - App name: "DMAF" (or your choice)
   - Scopes: None required (Photos API uses separate scope)
4. Create OAuth client:
   - Application type: "Desktop app"
   - Name: "DMAF Desktop Client"
5. Download credentials JSON file
6. **Rename to `client_secret.json`** and place in project root directory

### 3. First-Time Authentication

When you first run DMAF, it will:
1. Open your browser for Google authentication
2. Ask you to grant Photos Library access
3. Save `token.json` for future use (gitignored automatically)

**Security Note:** Both `client_secret.json` and `token.json` are automatically gitignored to protect your credentials.

---

## Email Alerts Setup (Optional)

Email alerts notify you about:
- **Borderline recognitions** - Near-miss matches that need manual review
- **Processing errors** - File read failures, API errors, etc.
- **Training updates** - New reference images added via auto-refresh

### Gmail Setup (Recommended)

#### Step 1: Enable 2-Step Verification
1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already enabled

#### Step 2: Generate App Password
1. Go to [App Passwords](https://myaccount.google.com/apppasswords)
2. Select:
   - App: **Mail**
   - Device: Your device/computer name
3. Click "Generate"
4. Copy the **16-character password** (format: `xxxx xxxx xxxx xxxx`)

#### Step 3: Configure DMAF

Add to your `config.yaml`:
```yaml
alerting:
  enabled: true
  recipients:
    - "your-email@gmail.com"
  batch_interval_minutes: 60  # Send batched alerts hourly
  borderline_offset: 0.1      # Alert if score within 0.1 of threshold
  event_retention_days: 90    # Clean up old events after 90 days
  smtp:
    host: "smtp.gmail.com"
    port: 587
    username: "your-email@gmail.com"
    password: "xxxxxxxxxxxxxxxx"  # Your 16-char App Password (no spaces)
    use_tls: true
    sender_email: "your-email@gmail.com"
```

**Security Note:** Your `config.yaml` is gitignored and never committed to version control.

### Alternative SMTP Servers

#### Outlook/Hotmail
```yaml
smtp:
  host: "smtp-mail.outlook.com"
  port: 587
  username: "your-email@outlook.com"
  password: "your-password"
  use_tls: true
  sender_email: "your-email@outlook.com"
```

#### Custom SMTP Server
```yaml
smtp:
  host: "smtp.your-domain.com"
  port: 587  # or 465 for SSL
  username: "your-username"
  password: "your-password"
  use_tls: true  # or false if using SSL on port 465
  sender_email: "noreply@your-domain.com"
```

### Understanding Email Alerts

**Batched Alerts (Default: Every 60 minutes)**
- Events accumulate in database
- Sent together at configured interval
- Prevents email spam during high-volume processing

**Borderline Recognitions**
- Triggered when similarity score is close to threshold
- Example: threshold=0.58, offset=0.1 → alert if score in [0.48, 0.58)
- Helps identify potential false negatives (missed recognitions)

**Error Notifications**
- Image loading failures
- API timeout errors
- Face detection errors
- Helps catch issues early

**Immediate Notifications (Not Batched)**
- Training refresh completions
- Critical system errors
- These bypass the batching interval

---

## Configuration

### 1. Add Reference Photos

Create directories for each person:
```bash
mkdir -p data/known_people/Alice
mkdir -p data/known_people/Bob
```

Add 3-5 clear photos per person:
```
data/known_people/
├── Alice/
│   ├── photo1.jpg
│   ├── photo2.jpg
│   └── photo3.jpg
└── Bob/
    ├── photo1.jpg
    └── photo2.jpg
```

**Photo Guidelines:**
- Clear, well-lit faces
- Multiple angles (front, side)
- Different expressions
- Minimum 3 photos per person (5-10 recommended)
- JPEG or PNG format

### 2. Create Configuration File

```bash
cp config.example.yaml config.yaml
```

### 3. Customize config.yaml

**Minimum Required Configuration:**
```yaml
# WhatsApp media directories
watch_dirs:
  - "/path/to/WhatsApp/Media/WhatsApp Images"

# Face recognition backend
recognition:
  backend: "insightface"  # or "face_recognition"
  tolerance: 0.42         # Lower = stricter matching

# Reference images
known_people_dir: "./data/known_people"
```

**Full Configuration with All Features:**
```yaml
# WhatsApp media directories
watch_dirs:
  - "/mnt/c/Users/YourName/WhatsApp/Media/WhatsApp Images"
  - "/mnt/c/Users/YourName/WhatsApp/Media/WhatsApp Video"

# Google Photos album (optional)
google_photos_album_name: "Family - Auto WhatsApp"

# Face recognition
recognition:
  backend: "insightface"
  tolerance: 0.42
  det_thresh: 0.4
  det_thresh_known: 0.3
  min_face_size_pixels: 80
  require_any_match: true
  return_best_only: true

# Reference images
known_people_dir: "./data/known_people"

# Deduplication
dedup:
  method: "sha256"
  backend: "sqlite"
  db_path: "./data/state.sqlite3"

# Email alerts
alerting:
  enabled: true
  recipients:
    - "your-email@gmail.com"
  batch_interval_minutes: 60
  borderline_offset: 0.1
  event_retention_days: 90
  smtp:
    host: "smtp.gmail.com"
    port: 587
    username: "your-email@gmail.com"
    password: "your-app-password-here"
    use_tls: true
    sender_email: "your-email@gmail.com"

# Auto-refresh training images
known_refresh:
  enabled: true
  interval_days: 60
  target_score: 0.65
  crop_padding_percent: 0.3

# Logging
log_level: "INFO"
```

---

## Running DMAF

### Standard Mode
```bash
dmaf --config config.yaml
```

Or:
```bash
python -m dmaf --config config.yaml
```

### Development Mode (Verbose Logging)
```bash
# Edit config.yaml and set:
log_level: "DEBUG"

# Then run:
dmaf --config config.yaml
```

### Running as Background Service

**Using systemd (Linux):**
```bash
# Create service file
sudo nano /etc/systemd/system/dmaf.service
```

```ini
[Unit]
Description=DMAF - Don't Miss A Face
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/DMAF
ExecStart=/home/your-username/DMAF/.venv/bin/dmaf --config config.yaml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable dmaf
sudo systemctl start dmaf

# Check status
sudo systemctl status dmaf

# View logs
sudo journalctl -u dmaf -f
```

**Using screen (Quick Background Run):**
```bash
# Start in detached screen
screen -dmS dmaf dmaf --config config.yaml

# Reattach to see output
screen -r dmaf

# Detach: Press Ctrl+A, then D
```

---

## Troubleshooting

### Authentication Issues

**Error: "client_secret.json not found"**
- Ensure file is in project root directory (same level as config.yaml)
- Check filename is exactly `client_secret.json` (not `client_secret (1).json`)

**Error: "Invalid OAuth credentials"**
- Download fresh credentials from Google Cloud Console
- Ensure OAuth client type is "Desktop app"
- Delete old `token.json` and re-authenticate

### Email Alert Issues

**Error: "SMTP authentication failed"**
- Gmail: Ensure 2-Step Verification is enabled
- Gmail: Use App Password, not regular password
- Check username/password have no typos
- Verify SMTP host/port are correct

**No emails received**
- Check spam/junk folder
- Verify recipient email in config.yaml
- Check `batch_interval_minutes` - may be waiting to batch
- Check database for pending events: `sqlite3 data/state.sqlite3 "SELECT COUNT(*) FROM borderline_events WHERE alerted=0;"`

**Error: "Connection refused" or "Timeout"**
- Check firewall allows outbound SMTP connections
- Try different port (587 vs 465)
- Verify network connectivity: `telnet smtp.gmail.com 587`

### Face Recognition Issues

**"No faces detected" for obvious faces**
- Lower `det_thresh` in config.yaml (try 0.3)
- Check image quality (resolution, lighting)
- Verify image format is supported (JPEG/PNG)

**Too many false positives (strangers uploaded)**
- Increase `tolerance` (make stricter)
- Switch to `insightface` backend (0.0% FPR in testing)
- Review reference photos - remove unclear/duplicate images

**Person not recognized despite good reference photos**
- Decrease `tolerance` (make more lenient)
- Add more reference photos (5-10 recommended)
- Include photos from different angles/lighting

### Performance Issues

**High CPU usage**
- Use `insightface` backend (12x faster than dlib)
- Enable GPU acceleration if available
- Reduce `min_face_size_pixels` to skip tiny faces

**High memory usage**
- Reduce number of reference photos per person
- Process fewer directories simultaneously
- Check for memory leaks: restart service periodically

### Database Issues

**Error: "Database locked"**
- Only one DMAF instance should run at a time
- Check for stale lock: `rm data/state.sqlite3-wal`
- Restart DMAF

**Database growing too large**
- Enable event retention cleanup: `event_retention_days: 90`
- Manually clean old events: `sqlite3 data/state.sqlite3 "DELETE FROM borderline_events WHERE alerted=1 AND created_ts < datetime('now', '-90 days');"`

---

## Security Best Practices

### Credentials
- ✅ Never commit `client_secret.json`, `token.json`, or `config.yaml`
- ✅ Use Gmail App Passwords instead of regular passwords
- ✅ Restrict file permissions: `chmod 600 config.yaml client_secret.json`
- ✅ Rotate credentials periodically (revoke old OAuth tokens)

### Data Privacy
- ✅ `data/` directory is fully gitignored (contains personal photos)
- ✅ Database contains file hashes and metadata only (no image data)
- ✅ Review Google Photos API permissions periodically
- ✅ Use `insightface` to minimize false positive uploads

### Network Security
- ✅ Use TLS for SMTP (default in config)
- ✅ Consider running on private network (no internet exposure needed)
- ✅ Monitor alert emails for suspicious activity

---

## Next Steps

Once DMAF is running:

1. **Monitor Initial Run**
   - Watch logs for errors
   - Check first batch of uploads in Google Photos
   - Verify alerts arrive correctly (if enabled)

2. **Tune Recognition**
   - Adjust `tolerance` based on results
   - Add more reference photos if needed
   - Review borderline alerts to catch missed faces

3. **Enable Auto-Refresh** (Optional)
   - After 60 days of operation
   - Automatically adds challenging training images
   - Improves accuracy as appearances change

4. **Set Up Automation**
   - Configure as systemd service (Linux)
   - Run on startup automatically
   - Set up log rotation

---

## Support

- **Issues/Bugs:** https://github.com/yhyatt/DMAF/issues
- **Discussions:** https://github.com/yhyatt/DMAF/discussions
- **Documentation:** See README.md for feature details

---

## Additional Resources

- [Google Photos Library API Docs](https://developers.google.com/photos/library/guides/get-started)
- [Gmail App Passwords Guide](https://support.google.com/accounts/answer/185833)
- [InsightFace Documentation](https://github.com/deepinsight/insightface)
- [DMAF Project Roadmap](IMPLEMENTATION_STATUS.md)
