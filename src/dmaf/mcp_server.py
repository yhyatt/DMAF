"""DMAF MCP Server — control plane for the DMAF pipeline.

Exposes DMAF operations as MCP tools so any MCP-capable AI client
(Claude Desktop, Claude Code, Cursor, etc.) can trigger scans, check
status, manage known people, and update config — without needing to
know gcloud or gsutil commands.

The underlying pipeline (sync cron + Cloud Run) stays token-free.
This server is a lightweight control plane only.

Configuration via environment variables:
    DMAF_PROJECT        GCP project ID (required)
    DMAF_REGION         Cloud Run region (default: us-central1)
    DMAF_JOB_NAME       Cloud Run job name (default: dmaf-scan)
    DMAF_MEDIA_BUCKET   GCS staging bucket URI (default: gs://{project}-whatsapp-media)
    DMAF_KNOWN_BUCKET   GCS known-people bucket URI (default: gs://{project}-known-people)
    DMAF_CONFIG_SECRET  Secret Manager secret name (default: dmaf-config)
    DMAF_SYNC_SCRIPT    Path to dmaf-sync.sh (default: ~/.openclaw/workspace/scripts/dmaf-sync.sh)

Usage:
    dmaf-mcp               # stdio transport (Claude Desktop / Claude Code)
    python -m dmaf.mcp_server
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dmaf", instructions=(
    "DMAF (Don't Miss A Face) control plane. "
    "Use these tools to operate the DMAF WhatsApp → face recognition → Google Photos pipeline. "
    "The pipeline itself runs token-free on GCP infrastructure; these tools let you manage it."
))


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _cfg() -> dict[str, str]:
    """Resolve runtime config from environment variables."""
    project = os.environ.get("DMAF_PROJECT", "")
    return {
        "project": project,
        "region": os.environ.get("DMAF_REGION", "us-central1"),
        "job": os.environ.get("DMAF_JOB_NAME", "dmaf-scan"),
        "media_bucket": os.environ.get(
            "DMAF_MEDIA_BUCKET", f"gs://{project}-whatsapp-media" if project else ""
        ),
        "known_bucket": os.environ.get(
            "DMAF_KNOWN_BUCKET", f"gs://{project}-known-people" if project else ""
        ),
        "config_secret": os.environ.get("DMAF_CONFIG_SECRET", "dmaf-config"),
        "sync_script": os.environ.get(
            "DMAF_SYNC_SCRIPT",
            os.path.expanduser("~/.openclaw/workspace/scripts/dmaf-sync.sh"),
        ),
    }


def _run(cmd: list[str], timeout: int = 60) -> tuple[str, str, int]:
    """Run a subprocess, return (stdout, stderr, returncode)."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _gcloud(*args: str, timeout: int = 60) -> tuple[str, str, int]:
    return _run(["gcloud", *args], timeout=timeout)


def _gsutil(*args: str, timeout: int = 60) -> tuple[str, str, int]:
    return _run(["gsutil", *args], timeout=timeout)


def _require_project(cfg: dict[str, str]) -> str | None:
    """Return an error string if DMAF_PROJECT is not set, else None."""
    if not cfg["project"]:
        return (
            "DMAF_PROJECT environment variable is not set. "
            "Set it to your GCP project ID (e.g. export DMAF_PROJECT=my-project)."
        )
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def trigger_scan() -> str:
    """Trigger a DMAF face recognition scan on the GCS staging bucket.

    Launches the Cloud Run job asynchronously. Returns immediately with the
    execution name — use get_status() to follow progress.
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    out, stderr, rc = _gcloud(
        "run", "jobs", "execute", cfg["job"],
        f"--region={cfg['region']}",
        f"--project={cfg['project']}",
        "--async",
        "--format=value(name)",
    )
    if rc != 0:
        return f"❌ Failed to trigger scan:\n{stderr}"
    exec_name = out.split("/")[-1] if out else "unknown"
    return f"✅ Scan triggered — execution: {exec_name}\nUse get_status() to check progress."


@mcp.tool()
def get_status(freshness: str = "1h") -> str:
    """Get the result of the most recent DMAF scan.

    Args:
        freshness: How far back to look for log entries (e.g. '30m', '1h', '6h').

    Returns a summary of processed/matched/uploaded/error counts.
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    out, stderr, rc = _gcloud(
        "logging", "read",
        f'resource.type="cloud_run_job" AND resource.labels.job_name="{cfg["job"]}"',
        f"--freshness={freshness}",
        "--limit=200",
        "--format=value(textPayload)",
        f"--project={cfg['project']}",
    )
    if rc != 0:
        return f"❌ Failed to read logs:\n{stderr}"
    if not out:
        return f"No log entries found in the last {freshness}. Has the job run recently?"

    lines = out.splitlines()
    # Surface summary lines and errors
    keywords = ("processed", "matched", "uploaded", "error", "scan complete", "starting")
    summary = [line for line in lines if any(kw in line.lower() for kw in keywords)]
    if summary:
        return "📊 Recent scan summary:\n" + "\n".join(summary[-20:])
    # Fall back to last N lines
    return "📋 Recent log lines (no summary found):\n" + "\n".join(lines[-15:])


@mcp.tool()
def get_logs(lines: int = 50, freshness: str = "1h") -> str:
    """Fetch raw Cloud Run job logs for debugging.

    Args:
        lines:     Number of log lines to return (default 50).
        freshness: How far back to look (e.g. '30m', '1h', '6h', '24h').
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    out, stderr, rc = _gcloud(
        "logging", "read",
        f'resource.type="cloud_run_job" AND resource.labels.job_name="{cfg["job"]}"',
        f"--freshness={freshness}",
        f"--limit={lines}",
        "--format=value(textPayload)",
        f"--project={cfg['project']}",
    )
    if rc != 0:
        return f"❌ Failed to read logs:\n{stderr}"
    if not out:
        return f"No log entries in the last {freshness}."
    return out


@mcp.tool()
def sync_now() -> str:
    """Run the WhatsApp → GCS media sync immediately (don't wait for the cron).

    Runs dmaf-sync.sh and reports how many files were uploaded.
    """
    cfg = _cfg()
    script = cfg["sync_script"]
    if not os.path.isfile(script):
        return (
            f"❌ Sync script not found at: {script}\n"
            "Set DMAF_SYNC_SCRIPT or ensure the script is installed at the default path."
        )
    out, stderr, rc = _run(["bash", script], timeout=120)
    result = out or stderr or "(no output)"
    if rc != 0:
        return f"❌ Sync failed (exit {rc}):\n{result}"
    return f"✅ Sync complete:\n{result}"


@mcp.tool()
def list_people() -> str:
    """List the people currently registered for face recognition.

    Returns the names (subdirectory names) in the known-people GCS bucket,
    along with the photo count for each.
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    bucket = cfg["known_bucket"]
    if not bucket:
        return "❌ DMAF_KNOWN_BUCKET is not set."
    out, stderr, rc = _gsutil("ls", bucket)
    if rc != 0:
        return f"❌ Failed to list known people:\n{stderr}"
    if not out:
        return "No people registered yet. Use add_person() to add reference photos."

    people: list[str] = []
    for line in out.splitlines():
        name = line.rstrip("/").split("/")[-1]
        if name:
            # Count photos
            sub_out, _, _ = _gsutil("ls", f"{bucket.rstrip('/')}/{name}/")
            count = len(sub_out.splitlines()) if sub_out else 0
            people.append(f"  • {name} ({count} photo{'s' if count != 1 else ''})")

    return "👥 Known people:\n" + "\n".join(people)


@mcp.tool()
def add_person(name: str, photo_paths: list[str]) -> str:
    """Add a new person (or more photos for an existing person) to face recognition.

    Args:
        name:        Person's name — becomes the subdirectory name in the known-people bucket.
        photo_paths: List of local file paths to upload as reference photos.

    The Cloud Run job downloads updated reference photos at the start of each scan,
    so no rebuild is needed — changes take effect on the next scan.
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    bucket = cfg["known_bucket"]
    if not bucket:
        return "❌ DMAF_KNOWN_BUCKET is not set."
    if not photo_paths:
        return "❌ No photo paths provided."

    dest = f"{bucket.rstrip('/')}/{name}/"
    results: list[str] = []
    failed = 0

    for path in photo_paths:
        if not os.path.isfile(path):
            results.append(f"  ✗ {path} — file not found")
            failed += 1
            continue
        filename = os.path.basename(path)
        _, stderr, rc = _gsutil("cp", path, f"{dest}{filename}")
        if rc != 0:
            results.append(f"  ✗ {filename} — {stderr}")
            failed += 1
        else:
            results.append(f"  ✓ {filename}")

    uploaded = len(photo_paths) - failed
    summary = f"👤 Added {uploaded}/{len(photo_paths)} photo(s) for '{name}' → {dest}"
    return summary + "\n" + "\n".join(results)


@mcp.tool()
def remove_person(name: str) -> str:
    """Remove a person from face recognition by deleting their reference photos.

    Args:
        name: The person's name (must match the subdirectory name exactly).

    This takes effect on the next scan — no rebuild needed.
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    bucket = cfg["known_bucket"]
    if not bucket:
        return "❌ DMAF_KNOWN_BUCKET is not set."
    target = f"{bucket.rstrip('/')}/{name}/"
    _, stderr, rc = _gsutil("-m", "rm", "-r", target)
    if rc != 0:
        return f"❌ Failed to remove '{name}':\n{stderr}"
    return f"✅ Removed '{name}' from known people. Takes effect on next scan."


@mcp.tool()
def get_config() -> str:
    """Fetch the current DMAF configuration from Secret Manager.

    Returns the full YAML config (sensitive values like passwords are included —
    treat the output accordingly).
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    out, stderr, rc = _gcloud(
        "secrets", "versions", "access", "latest",
        f"--secret={cfg['config_secret']}",
        f"--project={cfg['project']}",
    )
    if rc != 0:
        return f"❌ Failed to read config:\n{stderr}"
    return f"📄 Current DMAF config ({cfg['config_secret']}):\n\n{out}"


@mcp.tool()
def update_config(yaml_content: str) -> str:
    """Push a new DMAF configuration to Secret Manager.

    Args:
        yaml_content: Full YAML configuration string (use get_config() to fetch
                      the current config, edit it, then pass it here).

    Creates a new secret version — previous versions are retained and can be
    rolled back in the GCP console if needed.
    """
    cfg = _cfg()
    if err := _require_project(cfg):
        return err
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name
    try:
        out, stderr, rc = _gcloud(
            "secrets", "versions", "add", cfg["config_secret"],
            f"--data-file={tmp_path}",
            f"--project={cfg['project']}",
        )
    finally:
        os.unlink(tmp_path)
    if rc != 0:
        return f"❌ Failed to update config:\n{stderr}"
    version = out.strip() if out else "unknown"
    return f"✅ Config updated — new version: {version}\nTakes effect on next Cloud Run execution."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
