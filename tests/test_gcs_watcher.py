"""Tests for GCS watch directory support."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from dmaf.gcs_watcher import cleanup_temp_file, is_gcs_uri, parse_gcs_uri


class TestParseGcsUri:
    def test_bucket_only(self):
        assert parse_gcs_uri("gs://my-bucket") == ("my-bucket", "")

    def test_bucket_with_prefix(self):
        assert parse_gcs_uri("gs://my-bucket/some/prefix/") == ("my-bucket", "some/prefix/")

    def test_bucket_with_file(self):
        assert parse_gcs_uri("gs://my-bucket/path/to/file.jpg") == (
            "my-bucket",
            "path/to/file.jpg",
        )


class TestIsGcsUri:
    def test_gcs_uri(self):
        assert is_gcs_uri("gs://bucket") is True

    def test_local_path(self):
        assert is_gcs_uri("/tmp/local") is False

    def test_relative_path(self):
        assert is_gcs_uri("./relative") is False


class TestCleanupTempFile:
    def test_cleanup_existing(self, tmp_path):
        f = tmp_path / "test.jpg"
        f.write_bytes(b"data")
        cleanup_temp_file(f)
        assert not f.exists()

    def test_cleanup_missing_ok(self, tmp_path):
        f = tmp_path / "nonexistent.jpg"
        cleanup_temp_file(f)  # should not raise


class TestGcsScanIntegration:
    """Test that GCS paths are used as dedup keys, not temp paths."""

    @patch("dmaf.gcs_watcher._get_storage_client")
    def test_dedup_key_is_gcs_path(self, mock_get_client):
        """The database should store gs://... paths, not /tmp/... paths."""
        from dmaf.watcher import scan_and_process_once

        # Mock GCS to return one blob
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        mock_blob = MagicMock()
        mock_blob.name = "photos/test.jpg"
        mock_bucket.list_blobs.return_value = [mock_blob]

        # Create a real temp image for download
        import numpy as np
        from PIL import Image

        test_img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        test_img.save(tmp.name)
        tmp.close()

        # Mock blob download to copy our test image
        def fake_download(filename):
            import shutil
            shutil.copy(tmp.name, filename)

        mock_bucket.blob.return_value.download_to_filename = fake_download

        # Mock handler
        handler = MagicMock()
        handler.db_conn.seen.return_value = False
        handler.process_fn.return_value = (False, [], {})
        handler.cfg.delete_unmatched_after_processing = False
        handler.alert_manager = None

        result = scan_and_process_once(["gs://my-bucket/photos/"], handler)

        # Verify dedup key is the GCS path, not a temp path
        seen_call_arg = handler.db_conn.seen.call_args[0][0]
        assert seen_call_arg == "gs://my-bucket/photos/test.jpg"

        add_file_call_arg = handler.db_conn.add_file_with_score.call_args[0][0]
        assert add_file_call_arg == "gs://my-bucket/photos/test.jpg"
        assert not add_file_call_arg.startswith("/tmp")

        # Verify temp file was cleaned up
        # (the temp files created by download_gcs_blob should be removed)
        assert result.new_files == 1
        assert result.processed == 1

        # Clean up our test image
        Path(tmp.name).unlink(missing_ok=True)

    def test_local_dirs_unchanged(self, tmp_path):
        """Local directory scanning should work exactly as before."""
        from dmaf.watcher import scan_and_process_once

        import numpy as np
        from PIL import Image

        # Create a test image in local dir
        img_path = tmp_path / "test.jpg"
        test_img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        test_img.save(img_path)

        handler = MagicMock()
        handler.db_conn.seen.return_value = False
        handler.process_fn.return_value = (False, [], {})
        handler.cfg.delete_unmatched_after_processing = False
        handler.alert_manager = None

        result = scan_and_process_once([str(tmp_path)], handler)

        # Dedup key should be the local path
        seen_call_arg = handler.db_conn.seen.call_args[0][0]
        assert seen_call_arg == str(img_path)

        assert result.new_files == 1
        assert result.processed == 1
