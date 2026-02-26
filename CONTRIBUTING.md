# Contributing to DMAF

Thanks for your interest in contributing! 🦞

## Before You Start

- **Check existing issues** — your idea may already be tracked
- **Open an issue first** for significant changes — alignment before code saves everyone time
- Small fixes (typos, docs, test coverage) — PRs welcome directly

## Development Setup

```bash
git clone https://github.com/yhyatt/DMAF.git && cd DMAF
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all,dev]"
pre-commit install       # ruff + mypy run before every commit
```

## Workflow

1. Fork → feature branch (`git checkout -b feat/my-thing`)
2. Make changes
3. `pytest tests/ -v` — all tests pass
4. `ruff check src/ tests/` + `mypy src/dmaf` — no new errors
5. Open PR against `main`

## Code Standards

- **Python 3.10+** type hints throughout (`list[str]` not `List[str]`)
- **Pydantic** for any new config fields (add to `src/dmaf/config.py`)
- **Tests required** for new functionality — see `tests/` for mock patterns
- **Ruff** enforced in CI — run `ruff check --fix` before pushing
- **No hardcoded project IDs, emails, or personal data** anywhere

## Adding a Face Recognition Backend

1. Create `src/dmaf/face_recognition/your_backend.py`
2. Implement `load_known_faces(known_root, **params)` and `best_match(known_faces, img, **params)`
3. Register in `src/dmaf/face_recognition/factory.py`
4. Add optional dep to `pyproject.toml`
5. Add tests in `tests/test_face_recognition/`

See [`AGENTS.md`](AGENTS.md) for full architecture context.

## Questions?

Open a [GitHub Discussion](https://github.com/yhyatt/DMAF/discussions) or file an issue.
