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
- **WhatsApp media access** via one of:
  - **Dropbox Camera Upload** (iOS/Android) - Recommended, see [WhatsApp Media Sync Setup](#whatsapp-media-sync-setup)
  - **Android file sync** (Syncthing, FolderSync, etc.)
  - **WhatsApp Desktop** media folder
  - **WSL file system** mount (Windows)

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

## Email Alerts Setup (Optional but Recommended)

Email alerts notify you about:
- **Borderline recognitions** - Near-miss matches that need manual review
- **Processing errors** - File read failures, API errors, etc.
- **Training updates** - New reference images added via auto-refresh

### ⭐ SendGrid Setup (Recommended)

**Why SendGrid?**
- ✅ **Free forever**: 100 emails/day (plenty for DMAF)
- ✅ **Secure**: API keys instead of passwords, revoke anytime
- ✅ **No personal email risk**: Isolated from your Gmail/personal accounts
- ✅ **Better deliverability**: Professional email service
- ✅ **Industry standard**: Used by millions of apps

**Note:** Google is phasing out App Passwords for Gmail SMTP. SendGrid is the recommended modern alternative.

#### Step 1: Create SendGrid Account (2 minutes)

1. Go to [SendGrid Signup](https://signup.sendgrid.com/)
2. Fill in account details (free tier, no credit card required)
3. Verify your email address
4. Complete the onboarding survey (select "Technical" role)

#### Step 2: Verify Sender Email (2 minutes)

1. In SendGrid dashboard, go to **Settings** → **Sender Authentication**
2. Click **Verify a Single Sender**
3. Fill in your details:
   - **From Name**: "DMAF Alerts" (or your choice)
   - **From Email Address**: Your real email (e.g., `your-email@gmail.com`)
   - **Reply To**: Same as above
   - Company details: Can use personal info
4. Click **Create**
5. Check your email inbox for verification link
6. Click the verification link

**Important:** You'll send alerts FROM this verified email TO any recipients you configure.

#### Step 3: Create API Key (1 minute)

1. Go to **Settings** → **API Keys**
2. Click **Create API Key**
3. Name: "DMAF Email Alerts"
4. Permissions: **Restricted Access**
   - Expand **Mail Send** → Enable **Mail Send** (full access)
   - All other permissions: Leave disabled
5. Click **Create & View**
6. **Copy the API key** (starts with `SG.`) - you won't see it again!

#### Step 4: Configure DMAF

Add to your `config.yaml`:
```yaml
alerting:
  enabled: true
  recipients:
    - "your-email@gmail.com"      # Where you want to RECEIVE alerts
  batch_interval_minutes: 60       # Send batched alerts hourly
  borderline_offset: 0.1           # Alert if score within 0.1 of threshold
  event_retention_days: 90         # Clean up old events after 90 days
  smtp:
    host: "smtp.sendgrid.net"
    port: 587
    username: "apikey"             # Literal string "apikey"
    password: "SG.xxxxxxxxxxxxxxxxxxxx"  # Your SendGrid API Key from Step 3
    use_tls: true
    sender_email: "your-email@gmail.com"  # Must match verified sender from Step 2
```

#### Step 5: Test (Optional)

Run DMAF and trigger a test event, or manually test:
```bash
python -c "
from dmaf.alerting.email_sender import EmailSender
from dmaf.config import SmtpSettings

smtp = SmtpSettings(
    host='smtp.sendgrid.net',
    port=587,
    username='apikey',
    password='SG.your-key-here',
    use_tls=True,
    sender_email='your-verified-email@gmail.com'
)
sender = EmailSender(smtp)
success = sender.send_email(
    'your-email@gmail.com',
    'DMAF Test',
    'If you receive this, SendGrid is configured correctly!'
)
print('✅ Test email sent!' if success else '❌ Failed')
"
```

**That's it!** You now have secure, professional email alerts without risking your personal Gmail account.

---

### Alternative Email Options

#### Option 2: Dedicated Gmail Account (Simple, Isolated)

Create a **new** Gmail account just for DMAF alerts to isolate security risk.

**Why this works:**
- If DMAF or credentials are compromised, only this account is affected
- Your personal Gmail remains safe
- Free and familiar
- Takes 5 minutes to set up

**Setup:**
1. Create new Gmail: `dmaf-alerts-yourname@gmail.com`
2. Enable 2-Step Verification on the new account
3. Generate App Password:
   - Go to [App Passwords](https://myaccount.google.com/apppasswords)
   - Generate password for "Mail"
4. Configure DMAF:
```yaml
alerting:
  enabled: true
  recipients:
    - "your-real-email@gmail.com"  # Send TO your real email
  smtp:
    host: "smtp.gmail.com"
    port: 587
    username: "dmaf-alerts-yourname@gmail.com"  # Dedicated account
    password: "xxxx xxxx xxxx xxxx"  # App Password for dedicated account
    use_tls: true
    sender_email: "dmaf-alerts-yourname@gmail.com"
```

#### Option 3: Mailgun

Free tier: 5,000 emails/month for 3 months, then paid.

**Setup:**
1. Sign up at [Mailgun](https://signup.mailgun.com/new/signup)
2. Verify your email
3. Get SMTP credentials from **Sending** → **Domain Settings** → **SMTP**
4. Configure:
```yaml
smtp:
  host: "smtp.mailgun.org"
  port: 587
  username: "postmaster@sandbox123.mailgun.org"  # From Mailgun dashboard
  password: "your-mailgun-smtp-password"
  use_tls: true
  sender_email: "dmaf@sandbox123.mailgun.org"
```

#### Option 4: AWS SES (Advanced, Very Cheap)

For users already on AWS. **Pricing:** $0.10 per 1,000 emails.

**Setup:**
1. Create AWS account
2. Go to [Amazon SES Console](https://console.aws.amazon.com/ses/)
3. Verify email address in **Verified Identities**
4. Create SMTP credentials in **SMTP Settings**
5. Configure:
```yaml
smtp:
  host: "email-smtp.us-east-1.amazonaws.com"  # Adjust region
  port: 587
  username: "your-aws-smtp-username"
  password: "your-aws-smtp-password"
  use_tls: true
  sender_email: "your-verified@email.com"
```

#### Option 5: Skip Email Alerts (No Risk, Manual Checking)

If you prefer not to set up email, you can query events manually:

```bash
# View pending borderline recognitions
sqlite3 data/state.sqlite3 "
  SELECT file_path, match_score, matched_person, created_ts
  FROM borderline_events
  WHERE alerted=0
  ORDER BY created_ts DESC;
"

# View recent errors
sqlite3 data/state.sqlite3 "
  SELECT error_type, error_message, file_path, created_ts
  FROM error_events
  WHERE alerted=0
  ORDER BY created_ts DESC;
"

# Count unreviewed events
sqlite3 data/state.sqlite3 "
  SELECT
    (SELECT COUNT(*) FROM borderline_events WHERE alerted=0) as borderline,
    (SELECT COUNT(*) FROM error_events WHERE alerted=0) as errors;
"
```

Set `alerting.enabled: false` in config.yaml.

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

## WhatsApp Media Sync Setup

DMAF needs access to WhatsApp media files. Choose the method that best fits your setup:

### Option 1: WhatsApp Desktop + rclone (Recommended for All Platforms) ⭐

**Best for**: Cross-platform solution (iOS + Android), cloud DMAF deployment, zero duplicates

**Why WhatsApp Desktop?**
- ✅ Works with both iOS and Android phones
- ✅ **Pure WhatsApp media only** (no personal photos or screenshots)
- ✅ **Zero duplicates** (separate from phone's camera backup)
- ✅ Desktop continues working even when you switch phones
- ✅ Works with cloud DMAF deployment via rclone sync
- ⚠️ Requires desktop/laptop to be running periodically

**What you get**:
```
Camera photos → Phone → Google Photos app → Personal backup ✓
WhatsApp media → Phone → Desktop → rclone → DMAF → Filtered backup ✓

Zero overlap, zero duplicates!
```

#### Setup Steps

**1. Install WhatsApp Desktop**

Download from [whatsapp.com/download](https://www.whatsapp.com/download) and install on your Mac, Windows, or Linux machine.

**2. Link to Your Phone**
- Open WhatsApp Desktop
- Scan QR code with WhatsApp on your phone:
  - **iOS**: WhatsApp → Settings → Linked Devices → Link a Device
  - **Android**: WhatsApp → Three dots → Linked Devices → Link a Device

**3. Configure Auto-Download**
```
WhatsApp Desktop → Settings (gear icon) → Storage

Media auto-download:
✓ Photos (enable)
✓ Videos (enable if wanted, or disable to save space)
☐ Audio (optional)
☐ Documents (optional)

Download location: [Default is fine]
```

**Important**: Set WhatsApp Desktop to auto-start on login:
- **Mac**: System Preferences → Users & Groups → Login Items → Add WhatsApp
- **Windows**: Task Manager → Startup tab → Enable WhatsApp

**4. Install and Configure rclone**

**On Mac**:
```bash
# Install rclone
brew install rclone

# Configure rclone for your DMAF server destination
# For local server:
rclone config
# Choose: n (new remote)
# Name: dmaf-server
# Type: sftp (or smb, ftp, depending on your server)
# Host: your-server-ip
# Configure authentication

# Test sync
rclone sync ~/Library/Containers/WhatsApp/Data/Library/Application\ Support/WhatsApp/Media/ \
  dmaf-server:/path/to/dmaf/watch-dir/ --dry-run
```

**On Windows**:
```powershell
# Install rclone (download from rclone.org or use Chocolatey)
choco install rclone

# Configure rclone (same as Mac)
rclone config

# Test sync (adjust path - varies by WhatsApp version)
rclone sync "$env:LOCALAPPDATA\Packages\5319275A.WhatsAppDesktop_cv1g1gnamwj4y\LocalState\shared\transfers\" dmaf-server:/path/to/dmaf/watch-dir/ --dry-run
```

**5. Automate Sync**

**On Mac (using launchd)**:
```bash
# Create sync script
cat > ~/sync-whatsapp-to-dmaf.sh << 'EOF'
#!/bin/bash
rclone sync \
  ~/Library/Containers/WhatsApp/Data/Library/Application\ Support/WhatsApp/Media/ \
  dmaf-server:/path/to/dmaf/watch-dir/ \
  --log-file ~/rclone-whatsapp.log \
  --log-level INFO
EOF

chmod +x ~/sync-whatsapp-to-dmaf.sh

# Create launchd plist
cat > ~/Library/LaunchAgents/com.dmaf.whatsapp-sync.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dmaf.whatsapp-sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USERNAME/sync-whatsapp-to-dmaf.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

# Load the job (runs every hour)
launchctl load ~/Library/LaunchAgents/com.dmaf.whatsapp-sync.plist
```

**On Windows (using Task Scheduler)**:
```powershell
# Create scheduled task (runs every hour)
$action = New-ScheduledTaskAction -Execute "rclone.exe" -Argument "sync `"$env:LOCALAPPDATA\Packages\5319275A.WhatsAppDesktop_cv1g1gnamwj4y\LocalState\shared\transfers\`" dmaf-server:/path/to/dmaf/watch-dir/ --log-file C:\rclone-whatsapp.log"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName "DMAF WhatsApp Sync" -Action $action -Trigger $trigger -Description "Sync WhatsApp Desktop media to DMAF server"
```

**6. Configure DMAF**

```yaml
# In config.yaml
watch_dirs:
  - "/path/to/dmaf/watch-dir"  # Where rclone syncs to

# Safe settings - WhatsApp Desktop folder is pure WhatsApp content
delete_source_after_upload: true              # Delete after Google Photos upload
delete_unmatched_after_processing: true       # Safe - no personal photos
```

**7. Critical WhatsApp Settings on Phone**

To prevent duplicates, configure your phone:

**On Android**:
```
WhatsApp → Settings → Chats → Media visibility = OFF

This prevents WhatsApp media from copying to Gallery/Camera folder
```

**On iOS**:
```
WhatsApp → Settings → Chats → Save to Camera Roll = OFF

This prevents WhatsApp media from copying to Camera Roll
```

**Verify Google Photos app is NOT backing up WhatsApp**:
```
Google Photos app → Settings → Backup → Device folders

Make sure only Camera folder is enabled:
✓ Camera (DCIM/Camera/)
✗ WhatsApp Images (should NOT be checked)
✗ WhatsApp Video (should NOT be checked)
```

#### Limitations & Considerations

**Desktop Must Be Running**:
- WhatsApp Desktop needs to be open periodically
- Media downloads happen when Desktop is active
- Set to auto-start on login (see step 3 above)

**Chats Must Be Opened**:
- Media from unopened chats may not download automatically
- Solution: Open WhatsApp Desktop daily, scroll through chats
- Most active chats will auto-download media
- Completeness: ~95% with regular use

**Storage on Desktop**:
- WhatsApp Desktop media can grow to 10-50GB
- Optional cleanup strategies:
  - Use `rclone move` instead of `sync` (deletes after upload)
  - Manually clear: WhatsApp Desktop → Settings → Storage → Manage storage
  - Let DMAF delete from destination after processing

**Initial Backfill**:
- Desktop only syncs recent messages when first linked
- Historical media stays on phone only
- Fine for ongoing operation; export from phone if historical backfill needed

#### Data Flow
```
WhatsApp message received on phone
     ↓
Multi-device sync to WhatsApp Desktop
     ↓
Media auto-downloads (when chat opened or viewed recently)
     ↓
Saved to Desktop local folder
     ↓
rclone syncs Desktop → DMAF server (hourly)
     ↓
DMAF processes: face recognition filtering
     ↓
Matched photos → Google Photos
Unmatched photos → deleted

Camera photos on phone
     ↓
Google Photos app backup (separate path)
     ↓
Google Photos (no filtering, all personal photos)

Result: Zero duplicates, clean separation!
```

---

### Option 2: Direct Android Sync (Android Only)

**Best for**: Android users who want phone-based sync without desktop dependency

**✅ Advantages**:
- Syncs ONLY WhatsApp media folder (`/Android/media/com.whatsapp/`)
- No personal photos involved
- 100% complete (all WhatsApp media synced)
- No desktop required
- Real-time sync possible

**⚠️ Limitation**: Android only (doesn't work when you switch to iOS)

#### Option 2a: FolderSync Pro ($5, Recommended)

**Setup**:
1. Install [FolderSync Pro](https://play.google.com/store/apps/details?id=dk.tacit.android.foldersync.full) from Play Store
2. Configure sync account:
   - For local server: SFTP, SMB, FTP, WebDAV
   - For cloud: Can sync to your DMAF server
3. Create folder pair:
   - **Local folder**: `/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images/`
   - **Remote folder**: Your DMAF server watch directory
   - **Sync type**: "To remote folder" (upload only)
   - **Schedule**: Every 3 hours (or real-time)
4. Optional: Enable "Delete source files after sync" to save phone storage

**Configure phone**:
```
WhatsApp → Settings → Chats → Media visibility = OFF

Google Photos app → Settings → Backup → Device folders
✓ Camera only
✗ WhatsApp Images (disable)
```

**DMAF config**:
```yaml
watch_dirs:
  - "/path/to/synced/whatsapp/folder"

delete_source_after_upload: true
delete_unmatched_after_processing: true  # Safe - WhatsApp folder only
```

#### Option 2b: Syncthing-Fork (Free, LAN Only)

**Setup**:
1. Install [Syncthing-Fork](https://f-droid.org/en/packages/com.github.catfriend1.syncthingandroid/) from F-Droid
2. Configure sync folder: `/Android/media/com.whatsapp/WhatsApp/Media/`
3. Add DMAF server as sync target
4. Works over LAN or VPN (Tailscale/Zerotier)

**Pros**: Free, P2P, no cloud dependency
**Cons**: Requires LAN/VPN, battery optimization issues on some devices

---

### Option 3: Manual Export (Occasional Use)

**Best for**: Occasional batch imports, not continuous monitoring

1. In WhatsApp: Chat → More → Export Chat → Attach Media
2. Save ZIP file
3. Extract to DMAF watch directory
4. Run DMAF in scan-once mode: `dmaf --scan-once --config config.yaml`

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
  # Cloud staging example:
  # - "/home/user/dropbox-sync/Camera Uploads"

# Google Photos album (optional)
google_photos_album_name: "Family - Auto WhatsApp"

# Source file management
# Delete files after successful upload (useful for cloud staging like Dropbox)
# WARNING: Destructive - files are permanently deleted!
delete_source_after_upload: false  # Set to true for Dropbox/cloud staging

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
