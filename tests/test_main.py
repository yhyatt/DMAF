"""Tests for __main__ entry point."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from dmaf import __main__


class TestBuildProcessor:
    """Test build_processor function."""

    @patch("dmaf.__main__.load_known_faces")
    def test_build_processor(self, mock_load):
        """Test building a face recognition processor."""
        # Mock load_known_faces
        mock_encodings = {"alice": [[1, 2, 3]]}
        mock_people = ["alice"]
        mock_load.return_value = (mock_encodings, mock_people)

        # Build processor
        processor = __main__.build_processor(
            Path("/path/to/known_people"), "face_recognition", 0.5, 80
        )

        # Verify load_known_faces was called with expected parameters
        mock_load.assert_called_once_with(
            "/path/to/known_people",
            backend_name="face_recognition",
            min_face_size=80,
            det_thresh_known=0.3,
            return_best_only=True,
            db=None,
        )

        # Verify processor is callable
        assert callable(processor)

    @patch("dmaf.__main__.load_known_faces")
    @patch("dmaf.__main__.best_match")
    def test_processor_calls_best_match(self, mock_best_match, mock_load):
        """Test that processor function calls best_match."""
        import numpy as np

        mock_encodings = {"bob": [[4, 5, 6]]}
        mock_load.return_value = (mock_encodings, ["bob"])

        mock_best_match.return_value = (True, ["bob"])

        processor = __main__.build_processor(Path("/path/to/known_people"), "insightface", 0.4, 100)

        # Call processor
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)
        matched, who = processor(test_image)

        # Verify best_match was called with correct parameters
        mock_best_match.assert_called_once()
        call_kwargs = mock_best_match.call_args[1]
        assert call_kwargs["backend_name"] == "insightface"
        assert call_kwargs["tolerance"] == 0.4
        assert call_kwargs["min_face_size"] == 100

        assert matched is True
        assert who == ["bob"]


class TestMain:
    """Test main function."""

    def test_main_config_not_found(self, temp_dir: Path, capsys):
        """Test main with nonexistent config file."""
        nonexistent_config = temp_dir / "nonexistent.yaml"

        result = __main__.main(["--config", str(nonexistent_config)])

        assert result == 1

        captured = capsys.readouterr()
        assert "Configuration file not found" in captured.err
        assert "config.example.yaml" in captured.err

    def test_main_invalid_config(self, temp_dir: Path, capsys):
        """Test main with invalid config."""
        # Create invalid config (tolerance out of bounds)
        import yaml

        invalid_config = temp_dir / "invalid.yaml"
        data = {
            "recognition": {"tolerance": 2.0},  # Invalid: > 1.0
            "known_people_dir": str(temp_dir / "known_people"),
        }

        with open(invalid_config, "w") as f:
            yaml.dump(data, f)

        result = __main__.main(["--config", str(invalid_config)])

        assert result == 1

        captured = capsys.readouterr()
        assert "Invalid configuration" in captured.err

    @patch("dmaf.__main__.run_watch")
    @patch("dmaf.__main__.get_creds")
    @patch("dmaf.__main__.ensure_album")
    @patch("dmaf.__main__.get_database")
    @patch("dmaf.__main__.load_known_faces")
    def test_main_success(
        self,
        mock_load,
        mock_get_database,
        mock_ensure_album,
        mock_get_creds,
        mock_run_watch,
        sample_config_yaml: Path,
    ):
        """Test successful main execution."""
        # Setup mocks
        mock_load.return_value = ({"alice": []}, ["alice"])
        mock_db = Mock()
        mock_get_database.return_value = mock_db

        mock_creds = Mock()
        mock_get_creds.return_value = mock_creds

        mock_ensure_album.return_value = "album_id_123"

        # Run main (will start watcher, but we mocked it)
        result = __main__.main(["--config", str(sample_config_yaml)])

        # Verify initialization
        mock_get_creds.assert_called_once()
        mock_load.assert_called_once()
        mock_run_watch.assert_called_once()

        assert result == 0

    @patch("dmaf.__main__.run_watch")
    @patch("dmaf.__main__.get_creds")
    @patch("dmaf.__main__.ensure_album")
    @patch("dmaf.__main__.get_database")
    @patch("dmaf.__main__.load_known_faces")
    def test_main_no_album_name(
        self,
        mock_load,
        mock_get_database,
        mock_ensure_album,
        mock_get_creds,
        mock_run_watch,
        temp_dir: Path,
    ):
        """Test main with no album name (album_id should be None)."""
        # Create config without album name
        import yaml

        config = temp_dir / "config.yaml"
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        data = {
            "watch_dirs": [str(temp_dir / "watch")],
            "google_photos_album_name": None,
            "recognition": {
                "backend": "face_recognition",
                "tolerance": 0.5,
            },
            "known_people_dir": str(known_dir),
            "dedup": {
                "db_path": str(temp_dir / "state.sqlite3"),
            },
        }

        with open(config, "w") as f:
            yaml.dump(data, f)

        # Setup mocks
        mock_load.return_value = ({}, [])
        mock_get_database.return_value = Mock()
        mock_get_creds.return_value = Mock()

        # Run main
        __main__.main(["--config", str(config)])

        # ensure_album should NOT have been called
        mock_ensure_album.assert_not_called()

    @patch("dmaf.__main__.run_watch")
    @patch("dmaf.__main__.get_creds")
    @patch("dmaf.__main__.ensure_album")
    @patch("dmaf.__main__.get_database")
    @patch("dmaf.__main__.load_known_faces")
    def test_main_album_creation_fails(
        self,
        mock_load,
        mock_get_database,
        mock_ensure_album,
        mock_get_creds,
        mock_run_watch,
        sample_config_yaml: Path,
        caplog,
    ):
        """Test that album creation failure logs warning but continues."""
        # Setup mocks
        mock_load.return_value = ({}, [])
        mock_get_database.return_value = Mock()
        mock_get_creds.return_value = Mock()

        # Make ensure_album fail
        mock_ensure_album.side_effect = Exception("Album creation failed")

        # Run main
        __main__.main(["--config", str(sample_config_yaml)])

        # Should have logged warning
        assert "Album ensure failed" in caplog.text

        # Should still call run_watch (continues despite album failure)
        mock_run_watch.assert_called_once()


class TestUploader:
    """Test Uploader class (defined in main())."""

    @patch("dmaf.__main__.run_watch")
    @patch("dmaf.__main__.get_creds")
    @patch("dmaf.__main__.get_database")
    @patch("dmaf.__main__.load_known_faces")
    @patch("dmaf.__main__.Image.open")
    @patch("dmaf.__main__.upload_bytes")
    @patch("dmaf.__main__.create_media_item")
    def test_uploader_on_match(
        self,
        mock_create,
        mock_upload,
        mock_image_open,
        mock_load,
        mock_get_database,
        mock_get_creds,
        mock_run_watch,
        sample_config_yaml: Path,
        temp_dir: Path,
    ):
        """Test that Uploader.on_match uploads images."""
        # Setup mocks
        mock_load.return_value = ({}, [])

        mock_db = Mock()
        mock_get_database.return_value = mock_db

        mock_creds = Mock()
        mock_get_creds.return_value = mock_creds

        mock_img = Mock()
        mock_img_rgb = Mock()
        mock_img.convert.return_value = mock_img_rgb
        mock_image_open.return_value = mock_img

        mock_upload.return_value = "upload_token_xyz"
        mock_create.return_value = "media_item_123"

        # Capture the handler created in main()
        captured_handler = None

        def capture_handler(dirs, handler):
            nonlocal captured_handler
            captured_handler = handler

        mock_run_watch.side_effect = capture_handler

        # Run main to create Uploader
        __main__.main(["--config", str(sample_config_yaml)])

        assert captured_handler is not None

        # Test on_match
        test_file = temp_dir / "test.jpg"
        test_file.write_bytes(b"fake_image")
        who = ["Alice", "Bob"]

        captured_handler.on_match(test_file, who)

        # Verify upload workflow
        mock_image_open.assert_called_once_with(test_file)
        mock_img.convert.assert_called_once_with("RGB")
        mock_upload.assert_called_once()
        mock_create.assert_called_once()

        # Verify database was updated
        mock_db.mark_uploaded.assert_called_once_with(str(test_file))

        # Verify description includes names
        call_kwargs = mock_create.call_args[1]
        assert "description" in call_kwargs
        assert "Alice" in call_kwargs["description"]
        assert "Bob" in call_kwargs["description"]


class TestMainCLI:
    """Test CLI argument parsing."""

    def test_help_flag(self):
        """Test --help flag."""
        with pytest.raises(SystemExit) as exc_info:
            __main__.main(["--help"])

        assert exc_info.value.code == 0

    def test_config_short_flag(self, capsys):
        """Test -c short flag for config."""
        result = __main__.main(["-c", "/nonexistent/config.yaml"])

        assert result == 1
        captured = capsys.readouterr()
        assert "Configuration file not found" in captured.err
