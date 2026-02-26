# DMAF — Claude Code Guide

> See **[AGENTS.md](AGENTS.md)** for the full coding agent guide (architecture,
> codebase map, testing patterns, common pitfalls, deployment commands).

This file exists for Claude Code CLI compatibility. All substantive guidance is in `AGENTS.md`.

---

## Quick orientation

```bash
pytest tests/ -v -k "not slow"          # Run tests
ruff check src/ tests/                  # Lint
mypy src/dmaf                           # Type check
gcloud run jobs execute dmaf-scan --region=us-central1 --async  # Manual scan
```

For a new deployment, start with **[`deploy/setup-secrets.md`](deploy/setup-secrets.md)**.
