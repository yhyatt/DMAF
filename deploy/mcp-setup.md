# DMAF MCP Server Setup

The DMAF MCP server exposes your running pipeline as typed tools that any
MCP-capable AI client can call directly — Claude Desktop, Claude Code, Cursor,
Windsurf, and others.

The pipeline itself (sync cron + Cloud Run) stays **completely token-free**.
The MCP server is a lightweight control plane only — it wraps `gcloud` and
`gsutil` CLI calls so your AI can operate DMAF without needing to know the commands.

## Available Tools

| Tool | What it does |
|------|-------------|
| `trigger_scan()` | Launch a Cloud Run scan immediately (async) |
| `get_status(freshness)` | Summarise the most recent scan result from Cloud Logging |
| `get_logs(lines, freshness)` | Full raw log output for debugging |
| `sync_now()` | Run the WhatsApp → GCS media sync right now |
| `list_people()` | Show all registered people + photo counts |
| `add_person(name, photo_paths)` | Upload reference photos for a new person |
| `remove_person(name)` | Remove a person from face recognition |
| `get_config()` | Fetch current DMAF config from Secret Manager |
| `update_config(yaml)` | Push a new config version to Secret Manager |

---

## Prerequisites

```bash
# Install DMAF with MCP extras
pip install -e ".[mcp]"

# Authenticate gcloud (needed by the MCP server at runtime)
gcloud auth application-default login
gcloud config set project your-project-id

# Set required env var
export DMAF_PROJECT=your-project-id
```

Optional env vars (all have sensible defaults derived from `DMAF_PROJECT`):

| Variable | Default |
|----------|---------|
| `DMAF_REGION` | `us-central1` |
| `DMAF_JOB_NAME` | `dmaf-scan` |
| `DMAF_MEDIA_BUCKET` | `gs://{project}-whatsapp-media` |
| `DMAF_KNOWN_BUCKET` | `gs://{project}-known-people` |
| `DMAF_CONFIG_SECRET` | `dmaf-config` |
| `DMAF_SYNC_SCRIPT` | `~/.openclaw/workspace/scripts/dmaf-sync.sh` |

---

## Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "dmaf": {
      "command": "dmaf-mcp",
      "env": {
        "DMAF_PROJECT": "your-project-id"
      }
    }
  }
}
```

Restart Claude Desktop — DMAF tools appear in the tools panel.

---

## Claude Code (CLI)

```bash
# Add DMAF as an MCP server for this project
claude mcp add dmaf dmaf-mcp -e DMAF_PROJECT=your-project-id

# Or globally
claude mcp add --scope user dmaf dmaf-mcp -e DMAF_PROJECT=your-project-id
```

Then just ask Claude Code: *"Trigger a DMAF scan"* or *"Show me the latest DMAF results"*.

---

## Cursor / Windsurf

Add to your MCP config (`.cursor/mcp.json` or `.windsurf/mcp.json`):

```json
{
  "mcpServers": {
    "dmaf": {
      "command": "dmaf-mcp",
      "env": {
        "DMAF_PROJECT": "your-project-id"
      }
    }
  }
}
```

---

## Testing the Server

```bash
# Quick smoke test — list tools
DMAF_PROJECT=your-project-id python -c "
from dmaf.mcp_server import list_people, get_status
print(list_people())
print(get_status(freshness='24h'))
"

# Full test suite
pytest tests/test_mcp_server.py -v
```
