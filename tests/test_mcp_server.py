"""Tests for the DMAF MCP server tools.

All tests mock subprocess.run — no real GCP/gsutil calls are made.
Set DMAF_PROJECT via monkeypatch; all other env vars use their defaults.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dmaf.mcp_server import (
    _require_project,
    add_person,
    get_config,
    get_logs,
    get_status,
    list_people,
    remove_person,
    sync_now,
    trigger_scan,
    update_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


@pytest.fixture(autouse=True)
def dmaf_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake project ID for every test."""
    monkeypatch.setenv("DMAF_PROJECT", "test-project")
    monkeypatch.setenv("DMAF_REGION", "us-central1")
    monkeypatch.setenv("DMAF_JOB_NAME", "dmaf-scan")


# ---------------------------------------------------------------------------
# _require_project
# ---------------------------------------------------------------------------

class TestRequireProject:
    def test_returns_none_when_set(self) -> None:
        cfg = {"project": "my-project"}
        assert _require_project(cfg) is None

    def test_returns_error_when_empty(self) -> None:
        cfg = {"project": ""}
        result = _require_project(cfg)
        assert result is not None
        assert "DMAF_PROJECT" in result


# ---------------------------------------------------------------------------
# trigger_scan
# ---------------------------------------------------------------------------

class TestTriggerScan:
    def test_success(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(
            stdout="projects/test-project/locations/us-central1/jobs/dmaf-scan/executions/dmaf-scan-abc123"
        )):
            result = trigger_scan()
        assert "✅" in result
        assert "dmaf-scan-abc123" in result

    def test_gcloud_failure(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(
            stderr="ERROR: (gcloud.run.jobs.execute) PERMISSION_DENIED", returncode=1
        )):
            result = trigger_scan()
        assert "❌" in result
        assert "PERMISSION_DENIED" in result

    def test_missing_project(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_PROJECT", "")
        result = trigger_scan()
        assert "DMAF_PROJECT" in result


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_parses_summary_lines(self) -> None:
        log_output = "\n".join([
            "Starting scan...",
            "Loading known people: 3 people, 41 photos",
            "Files processed: 12, matched: 3, uploaded: 3, errors: 0",
            "Scan complete in 47.2s",
            "Some unrelated line",
        ])
        with patch("subprocess.run", return_value=_mock_proc(stdout=log_output)):
            result = get_status()
        assert "📊" in result
        assert "processed" in result.lower()
        assert "matched" in result.lower()

    def test_empty_logs(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(stdout="")):
            result = get_status()
        assert "No log entries" in result

    def test_gcloud_failure(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(
            stderr="API error", returncode=1
        )):
            result = get_status()
        assert "❌" in result

    def test_fallback_to_raw_lines_when_no_summary(self) -> None:
        log_output = "line1\nline2\nline3"
        with patch("subprocess.run", return_value=_mock_proc(stdout=log_output)):
            result = get_status()
        # Falls back to raw lines
        assert "line" in result


# ---------------------------------------------------------------------------
# get_logs
# ---------------------------------------------------------------------------

class TestGetLogs:
    def test_returns_log_output(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(stdout="log line 1\nlog line 2")):
            result = get_logs(lines=10, freshness="30m")
        assert "log line 1" in result

    def test_empty(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(stdout="")):
            result = get_logs()
        assert "No log entries" in result


# ---------------------------------------------------------------------------
# sync_now
# ---------------------------------------------------------------------------

class TestSyncNow:
    def test_success(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        script = tmp_path / "dmaf-sync.sh"
        script.write_text("#!/bin/bash\necho 'Synced: 5 | Failed: 0'")
        monkeypatch.setenv("DMAF_SYNC_SCRIPT", str(script))
        with patch("subprocess.run", return_value=_mock_proc(stdout="Synced: 5 | Failed: 0")):
            result = sync_now()
        assert "✅" in result
        assert "Synced" in result

    def test_script_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_SYNC_SCRIPT", "/nonexistent/dmaf-sync.sh")
        result = sync_now()
        assert "❌" in result
        assert "not found" in result

    def test_script_failure(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        script = tmp_path / "dmaf-sync.sh"
        script.write_text("#!/bin/bash\nexit 1")
        monkeypatch.setenv("DMAF_SYNC_SCRIPT", str(script))
        with patch("subprocess.run", return_value=_mock_proc(stderr="gsutil error", returncode=1)):
            result = sync_now()
        assert "❌" in result


# ---------------------------------------------------------------------------
# list_people
# ---------------------------------------------------------------------------

class TestListPeople:
    def test_lists_people_with_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")

        def fake_run(cmd, **kwargs):
            if "gs://test-project-known-people" in cmd and len(cmd) == 3:
                # Top-level ls
                return _mock_proc(stdout="gs://test-project-known-people/Alice/\ngs://test-project-known-people/Bob/")
            # Per-person ls
            return _mock_proc(stdout="gs://test-project-known-people/Alice/photo1.jpg\ngs://test-project-known-people/Alice/photo2.jpg")

        with patch("subprocess.run", side_effect=fake_run):
            result = list_people()

        assert "Alice" in result
        assert "Bob" in result
        assert "👥" in result

    def test_empty_bucket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        with patch("subprocess.run", return_value=_mock_proc(stdout="")):
            result = list_people()
        assert "No people" in result

    def test_gsutil_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        with patch("subprocess.run", return_value=_mock_proc(stderr="Access denied", returncode=1)):
            result = list_people()
        assert "❌" in result


# ---------------------------------------------------------------------------
# add_person
# ---------------------------------------------------------------------------

class TestAddPerson:
    def test_success(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        photo = tmp_path / "alice.jpg"
        photo.write_bytes(b"fake-jpeg")

        with patch("subprocess.run", return_value=_mock_proc()):
            result = add_person("Alice", [str(photo)])

        assert "Alice" in result
        assert "✓" in result

    def test_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        result = add_person("Alice", ["/nonexistent/photo.jpg"])
        assert "✗" in result
        assert "not found" in result

    def test_empty_photo_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        result = add_person("Alice", [])
        assert "❌" in result

    def test_partial_failure(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        good = tmp_path / "good.jpg"
        good.write_bytes(b"fake-jpeg")

        def fake_run(cmd, **kwargs):
            if "good.jpg" in str(cmd):
                return _mock_proc()
            return _mock_proc(stderr="upload error", returncode=1)

        with patch("subprocess.run", side_effect=fake_run):
            result = add_person("Alice", [str(good), "/bad/photo.jpg"])

        assert "1/2" in result


# ---------------------------------------------------------------------------
# remove_person
# ---------------------------------------------------------------------------

class TestRemovePerson:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        with patch("subprocess.run", return_value=_mock_proc()):
            result = remove_person("Alice")
        assert "✅" in result
        assert "Alice" in result

    def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DMAF_KNOWN_BUCKET", "gs://test-project-known-people")
        with patch("subprocess.run", return_value=_mock_proc(stderr="No URLs matched", returncode=1)):  # noqa: E501
            result = remove_person("Nonexistent")
        assert "❌" in result


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_returns_yaml(self) -> None:
        yaml_content = "watch_dirs:\n  - gs://test/\nrecognition:\n  backend: auraface"
        with patch("subprocess.run", return_value=_mock_proc(stdout=yaml_content)):
            result = get_config()
        assert "watch_dirs" in result
        assert "📄" in result

    def test_failure(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(
            stderr="Secret not found", returncode=1
        )):
            result = get_config()
        assert "❌" in result


# ---------------------------------------------------------------------------
# update_config
# ---------------------------------------------------------------------------

class TestUpdateConfig:
    def test_success(self) -> None:
        new_yaml = "watch_dirs:\n  - gs://test/\n"
        with patch("subprocess.run", return_value=_mock_proc(
            stdout="Created version [3] of the secret [dmaf-config]."
        )):
            result = update_config(new_yaml)
        assert "✅" in result

    def test_failure(self) -> None:
        with patch("subprocess.run", return_value=_mock_proc(
            stderr="Permission denied", returncode=1
        )):
            result = update_config("bad: yaml")
        assert "❌" in result
