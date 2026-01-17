"""Tests for file system watcher and image handler."""

import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from dmaf.watcher import NewImageHandler, run_watch, sha256_of_file


class TestSha256OfFile:
    """Test SHA256 file hashing."""

    def test_sha256_of_empty_file(self, temp_dir: Path):
        """Test hashing an empty file."""
        empty_file = temp_dir / "empty.txt"
        empty_file.write_bytes(b"")

        file_hash = sha256_of_file(empty_file)

        # SHA256 of empty file
        expected = hashlib.sha256(b"").hexdigest()
        assert file_hash == expected

    def test_sha256_of_file_with_content(self, temp_dir: Path):
        """Test hashing a file with content."""
        test_file = temp_dir / "test.txt"
        content = b"Hello, World!"
        test_file.write_bytes(content)

        file_hash = sha256_of_file(test_file)

        expected = hashlib.sha256(content).hexdigest()
        assert file_hash == expected

    def test_sha256_of_large_file(self, temp_dir: Path):
        """Test hashing a large file (tests chunked reading)."""
        large_file = temp_dir / "large.bin"
        # Create 5 MB file
        content = b"x" * (5 * 1024 * 1024)
        large_file.write_bytes(content)

        file_hash = sha256_of_file(large_file)

        expected = hashlib.sha256(content).hexdigest()
        assert file_hash == expected


class TestNewImageHandlerInit:
    """Test NewImageHandler initialization."""

    def test_init(self):
        """Test handler initialization."""
        process_fn = Mock()
        db_conn = Mock()
        cfg = {"test": "config"}

        handler = NewImageHandler(process_fn, db_conn, cfg)

        assert handler.process_fn == process_fn
        assert handler.db_conn == db_conn
        assert handler.cfg == cfg


class TestNewImageHandlerOnCreated:
    """Test file creation event handling."""

    @patch("dmaf.watcher.time.sleep")
    def test_ignore_directory_events(self, mock_sleep):
        """Test that directory creation events are ignored."""
        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)

        event = Mock()
        event.is_directory = True
        event.src_path = "/path/to/directory"

        handler.on_created(event)

        # Should not sleep or process
        mock_sleep.assert_not_called()

    @patch("dmaf.watcher.time.sleep")
    def test_ignore_non_image_files(self, mock_sleep):
        """Test that non-image files are ignored."""
        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)

        for ext in [".txt", ".pdf", ".doc", ".zip", ".mp4"]:
            event = Mock()
            event.is_directory = False
            event.src_path = f"/path/to/file{ext}"

            handler.on_created(event)

        # Should not have processed any files
        mock_sleep.assert_not_called()

    @patch("dmaf.watcher.time.sleep")
    @patch.object(NewImageHandler, "_handle_file")
    def test_process_image_files(self, mock_handle, mock_sleep):
        """Test that image files are processed."""
        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)

        for ext in [".jpg", ".jpeg", ".png", ".heic", ".webp", ".JPG", ".PNG"]:
            event = Mock()
            event.is_directory = False
            event.src_path = f"/path/to/photo{ext}"

            handler.on_created(event)

        # Should have processed all image files
        assert mock_handle.call_count == 7
        # Should wait for file to finish writing
        assert mock_sleep.call_count == 7
        mock_sleep.assert_called_with(0.8)

    @patch("dmaf.watcher.time.sleep")
    @patch.object(NewImageHandler, "_handle_file")
    def test_exception_handling(self, mock_handle, mock_sleep):
        """Test that exceptions in _handle_file are caught and logged."""
        mock_handle.side_effect = Exception("Test error")

        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)

        event = Mock()
        event.is_directory = False
        event.src_path = "/path/to/photo.jpg"

        # Should not raise exception
        handler.on_created(event)

        mock_handle.assert_called_once()


class TestNewImageHandlerHandleFile:
    """Test individual file processing."""

    def test_skip_already_seen_file(self, temp_dir: Path):
        """Test that already-processed files are skipped."""
        db_conn = Mock()
        db_conn.seen.return_value = True

        process_fn = Mock()
        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(process_fn, db_conn, cfg)

        test_file = temp_dir / "test.jpg"
        test_file.write_bytes(b"fake_image")

        handler._handle_file(test_file)

        # Should check database
        db_conn.seen.assert_called_once_with(str(test_file))

        # Should not process
        process_fn.assert_not_called()
        db_conn.add_file.assert_not_called()

    @patch("dmaf.watcher.Image.open")
    def test_skip_corrupted_image(self, mock_image_open, temp_dir: Path):
        """Test that corrupted images are skipped."""
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_image_open.side_effect = Exception("Corrupted image")

        process_fn = Mock()
        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(process_fn, db_conn, cfg)

        test_file = temp_dir / "corrupted.jpg"
        test_file.write_bytes(b"corrupted_data")

        # Should not raise exception
        handler._handle_file(test_file)

        # Should not have added to database
        db_conn.add_file.assert_not_called()

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_process_matched_image(self, mock_sha256, mock_image_open, temp_dir: Path):
        """Test processing an image that matches a known person."""
        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "abc123hash"

        # Mock process_fn to return a match
        process_fn = Mock()
        process_fn.return_value = (True, ["Alice", "Bob"])

        # Config with delete disabled (default)
        cfg = Mock()
        cfg.delete_source_after_upload = False

        handler = NewImageHandler(process_fn, db_conn, cfg)

        # Mock on_match
        handler.on_match = Mock()

        test_file = temp_dir / "photo.jpg"
        test_file.write_bytes(b"fake_image_data")

        # Process file
        handler._handle_file(test_file)

        # Verify image was opened and converted to RGB
        mock_image_open.assert_called_once_with(test_file)
        mock_img.convert.assert_called_once_with("RGB")

        # Verify process_fn was called
        process_fn.assert_called_once()
        call_arg = process_fn.call_args[0][0]
        assert isinstance(call_arg, (np.ndarray, Mock))

        # Verify database was updated with scores
        db_conn.add_file_with_score.assert_called_once_with(
            str(test_file),
            "abc123hash",
            1,  # matched=True -> 1
            0,  # uploaded=False -> 0
            None,  # best_score (not returned in test mock)
            None,  # matched_person (not set for old format)
        )

        # Verify on_match was called
        handler.on_match.assert_called_once_with(test_file, ["Alice", "Bob"])

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_process_unmatched_image(self, mock_sha256, mock_image_open, temp_dir: Path):
        """Test processing an image that doesn't match any known person."""
        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "def456hash"

        # Mock process_fn to return no match
        process_fn = Mock()
        process_fn.return_value = (False, [])

        # Config with delete disabled (default)
        cfg = Mock()
        cfg.delete_source_after_upload = False

        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        test_file = temp_dir / "stranger.jpg"
        test_file.write_bytes(b"fake_image_data")

        # Process file
        handler._handle_file(test_file)

        # Verify database was updated with matched=0 and scores
        db_conn.add_file_with_score.assert_called_once_with(
            str(test_file),
            "def456hash",
            0,  # matched=False -> 0
            0,  # uploaded=False -> 0
            None,  # best_score (not returned in test mock)
            None,  # matched_person
        )

        # Verify on_match was NOT called
        handler.on_match.assert_not_called()


class TestNewImageHandlerOnMatch:
    """Test on_match callback."""

    def test_on_match_default(self, temp_dir: Path):
        """Test that default on_match does nothing."""
        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)

        test_file = temp_dir / "photo.jpg"
        who = ["Alice"]

        # Should not raise exception
        handler.on_match(test_file, who)


class TestRunWatch:
    """Test watchdog observer setup."""

    @patch("dmaf.watcher.Observer")
    @patch("dmaf.watcher.time.sleep")
    def test_run_watch_single_directory(self, mock_sleep, mock_observer_class, temp_dir: Path):
        """Test watching a single directory."""
        watch_dir = temp_dir / "watch"

        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)

        # Simulate KeyboardInterrupt after first sleep
        mock_sleep.side_effect = KeyboardInterrupt()

        run_watch([str(watch_dir)], handler)

        # Verify directory was created
        assert watch_dir.exists()

        # Verify observer was started
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()

        # Verify observer was stopped and joined
        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once()

    @patch("dmaf.watcher.Observer")
    @patch("dmaf.watcher.time.sleep")
    def test_run_watch_multiple_directories(self, mock_sleep, mock_observer_class, temp_dir: Path):
        """Test watching multiple directories."""
        watch_dirs = [
            temp_dir / "watch1",
            temp_dir / "watch2",
            temp_dir / "watch3",
        ]

        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)

        mock_sleep.side_effect = KeyboardInterrupt()

        run_watch([str(d) for d in watch_dirs], handler)

        # Verify all directories were created
        for d in watch_dirs:
            assert d.exists()

        # Verify observer.schedule was called for each directory
        assert mock_observer.schedule.call_count == 3

    @patch("dmaf.watcher.Observer")
    @patch("dmaf.watcher.time.sleep")
    def test_run_watch_creates_nested_directories(
        self, mock_sleep, mock_observer_class, temp_dir: Path
    ):
        """Test that nested directories are created."""
        nested_dir = temp_dir / "parent" / "child" / "grandchild"

        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)
        mock_sleep.side_effect = KeyboardInterrupt()

        run_watch([str(nested_dir)], handler)

        # Verify nested directory was created
        assert nested_dir.exists()

    @patch("dmaf.watcher.Observer")
    @patch("dmaf.watcher.time.sleep")
    def test_run_watch_non_recursive(self, mock_sleep, mock_observer_class, temp_dir: Path):
        """Test that watching is non-recursive."""
        watch_dir = temp_dir / "watch"

        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(Mock(), Mock(), cfg)
        mock_sleep.side_effect = KeyboardInterrupt()

        run_watch([str(watch_dir)], handler)

        # Verify recursive=False was passed to schedule
        call_kwargs = mock_observer.schedule.call_args[1]
        assert call_kwargs["recursive"] is False


class TestWatcherIntegration:
    """Test integration between watcher components."""

    @patch("dmaf.watcher.time.sleep")
    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_full_workflow(self, mock_sha256, mock_image_open, mock_sleep, temp_dir: Path):
        """Test complete workflow: event -> process -> database."""
        # Setup
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "integration_test_hash"

        process_fn = Mock()
        process_fn.return_value = (True, ["TestPerson"])

        cfg = Mock()
        cfg.delete_source_after_upload = False
        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        # Create test file
        test_file = temp_dir / "integration_test.jpg"
        test_file.write_bytes(b"test_image_data")

        # Simulate file creation event
        event = Mock()
        event.is_directory = False
        event.src_path = str(test_file)

        handler.on_created(event)

        # Verify full workflow
        db_conn.seen.assert_called_once()
        process_fn.assert_called_once()
        db_conn.add_file_with_score.assert_called_once()
        handler.on_match.assert_called_once()


class TestDeleteSourceAfterUpload:
    """Test delete source after upload feature."""

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_delete_source_enabled_watch_mode(self, mock_sha256, mock_image_open, temp_dir: Path):
        """Test file is deleted after match when delete_source_after_upload=True (watch mode)."""
        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "test_hash"

        process_fn = Mock()
        process_fn.return_value = (True, ["Alice"])

        # Config with delete enabled
        cfg = Mock()
        cfg.delete_source_after_upload = True

        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        # Create test file
        test_file = temp_dir / "to_delete.jpg"
        test_file.write_bytes(b"fake_image")

        # Process file
        handler._handle_file(test_file)

        # Verify file was deleted
        assert not test_file.exists()

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_delete_source_disabled_watch_mode(self, mock_sha256, mock_image_open, temp_dir: Path):
        """Test file is NOT deleted when delete_source_after_upload=False (watch mode)."""
        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "test_hash"

        process_fn = Mock()
        process_fn.return_value = (True, ["Alice"])

        # Config with delete disabled
        cfg = Mock()
        cfg.delete_source_after_upload = False

        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        # Create test file
        test_file = temp_dir / "to_keep.jpg"
        test_file.write_bytes(b"fake_image")

        # Process file
        handler._handle_file(test_file)

        # Verify file still exists
        assert test_file.exists()

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_delete_source_no_match_watch_mode(self, mock_sha256, mock_image_open, temp_dir: Path):
        """Test file is NOT deleted when no match (watch mode)."""
        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "test_hash"

        process_fn = Mock()
        process_fn.return_value = (False, [])  # No match

        # Config with delete_source_after_upload enabled, but delete_unmatched disabled
        cfg = Mock()
        cfg.delete_source_after_upload = True
        cfg.delete_unmatched_after_processing = False  # Only delete on match

        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        # Create test file
        test_file = temp_dir / "no_match.jpg"
        test_file.write_bytes(b"fake_image")

        # Process file
        handler._handle_file(test_file)

        # Verify file still exists (only delete on match)
        assert test_file.exists()

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_delete_source_failure_logged_watch_mode(
        self, mock_sha256, mock_image_open, temp_dir: Path, caplog
    ):
        """Test deletion failure is logged but doesn't crash (watch mode)."""
        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "test_hash"

        process_fn = Mock()
        process_fn.return_value = (True, ["Alice"])

        # Config with delete enabled
        cfg = Mock()
        cfg.delete_source_after_upload = True

        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        # Create test file
        test_file = temp_dir / "delete_will_fail.jpg"
        test_file.write_bytes(b"fake_image")

        # Mock unlink to raise exception
        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            # Process file - should not crash
            handler._handle_file(test_file)

        # Verify warning was logged
        assert "Failed to delete" in caplog.text
        assert "Permission denied" in caplog.text

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_delete_source_enabled_batch_mode(self, mock_sha256, mock_image_open, temp_dir: Path):
        """Test file is deleted after match in batch mode."""
        from dmaf.watcher import scan_and_process_once

        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "test_hash"

        process_fn = Mock()
        process_fn.return_value = (True, ["Bob"])

        # Config with delete enabled
        cfg = Mock()
        cfg.delete_source_after_upload = True

        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        # Create test file in watch directory
        watch_dir = temp_dir / "watch"
        watch_dir.mkdir()
        test_file = watch_dir / "batch_delete.jpg"
        test_file.write_bytes(b"fake_image")

        # Run batch scan
        result = scan_and_process_once([str(watch_dir)], handler)

        # Verify file was deleted
        assert not test_file.exists()
        assert result.matched == 1
        assert result.uploaded == 1

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_delete_source_disabled_batch_mode(self, mock_sha256, mock_image_open, temp_dir: Path):
        """Test file is NOT deleted in batch mode when disabled."""
        from dmaf.watcher import scan_and_process_once

        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "test_hash"

        process_fn = Mock()
        process_fn.return_value = (True, ["Bob"])

        # Config with delete disabled
        cfg = Mock()
        cfg.delete_source_after_upload = False

        handler = NewImageHandler(process_fn, db_conn, cfg)
        handler.on_match = Mock()

        # Create test file in watch directory
        watch_dir = temp_dir / "watch"
        watch_dir.mkdir()
        test_file = watch_dir / "batch_keep.jpg"
        test_file.write_bytes(b"fake_image")

        # Run batch scan
        result = scan_and_process_once([str(watch_dir)], handler)

        # Verify file still exists
        assert test_file.exists()
        assert result.matched == 1

    @patch("dmaf.watcher.Image.open")
    @patch("dmaf.watcher.sha256_of_file")
    def test_delete_source_upload_failure_batch_mode(
        self, mock_sha256, mock_image_open, temp_dir: Path
    ):
        """Test file is NOT deleted when upload fails in batch mode."""
        from dmaf.watcher import scan_and_process_once

        # Setup mocks
        db_conn = Mock()
        db_conn.seen.return_value = False

        mock_img = Mock(spec=Image.Image)
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_sha256.return_value = "test_hash"

        process_fn = Mock()
        process_fn.return_value = (True, ["Bob"])

        # Config with delete enabled
        cfg = Mock()
        cfg.delete_source_after_upload = True

        handler = NewImageHandler(process_fn, db_conn, cfg)
        # Make on_match raise exception (upload failure)
        handler.on_match = Mock(side_effect=Exception("Upload failed"))

        # Create test file in watch directory
        watch_dir = temp_dir / "watch"
        watch_dir.mkdir()
        test_file = watch_dir / "upload_fail.jpg"
        test_file.write_bytes(b"fake_image")

        # Run batch scan
        result = scan_and_process_once([str(watch_dir)], handler)

        # Verify file still exists (upload failed, so don't delete)
        assert test_file.exists()
        assert result.errors == 1
        assert result.uploaded == 0
