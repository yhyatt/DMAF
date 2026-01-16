"""Tests for known people refresh functionality."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest
from PIL import Image

from dmaf.config import KnownRefreshSettings
from dmaf.database import Database
from dmaf.known_refresh import KnownRefreshManager, RefreshCandidate, RefreshResult


class TestRefreshCandidateDataclass:
    """Test RefreshCandidate dataclass."""

    def test_create_candidate(self):
        """Test creating a RefreshCandidate."""
        candidate = RefreshCandidate(
            person_name="Alice",
            source_path="/test/img.jpg",
            match_score=0.67,
            score_delta=0.02,
        )

        assert candidate.person_name == "Alice"
        assert candidate.source_path == "/test/img.jpg"
        assert candidate.match_score == 0.67
        assert candidate.score_delta == 0.02


class TestRefreshResultDataclass:
    """Test RefreshResult dataclass."""

    def test_create_result(self):
        """Test creating a RefreshResult."""
        result = RefreshResult(
            person_name="Alice",
            source_file_path="/test/img.jpg",
            target_file_path="/known/alice/refresh.jpg",
            match_score=0.67,
            target_score=0.65,
        )

        assert result.person_name == "Alice"
        assert result.source_file_path == "/test/img.jpg"
        assert result.target_file_path == "/known/alice/refresh.jpg"
        assert result.match_score == 0.67
        assert result.target_score == 0.65


class TestKnownRefreshManager:
    """Test KnownRefreshManager class."""

    @pytest.fixture
    def mock_db(self, mock_db_path: Path):
        """Create a mock database for testing."""
        return Database(str(mock_db_path))

    @pytest.fixture
    def refresh_config(self):
        """Create refresh configuration."""
        return KnownRefreshSettings(
            enabled=True, interval_days=60, target_score=0.65, crop_padding_percent=0.3
        )

    @pytest.fixture
    def known_people_dir(self, temp_dir: Path):
        """Create known_people directory structure."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        # Create person directories
        (known_dir / "Alice").mkdir()
        (known_dir / "Bob").mkdir()

        return known_dir

    def test_init(self, mock_db, refresh_config, known_people_dir):
        """Test KnownRefreshManager initialization."""
        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        assert manager.config == refresh_config
        assert manager.db == mock_db
        assert manager.known_people_dir == known_people_dir
        assert manager.backend_name == "insightface"

    def test_should_refresh_enabled_false(self, mock_db, known_people_dir):
        """Test should_refresh returns False when disabled."""
        config = KnownRefreshSettings(enabled=False)
        manager = KnownRefreshManager(config, mock_db, known_people_dir, "insightface")

        result = manager.should_refresh()

        assert result is False

    def test_should_refresh_no_previous_refresh(self, mock_db, refresh_config, known_people_dir):
        """Test should_refresh returns True when no previous refresh."""
        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        result = manager.should_refresh()

        assert result is True

    def test_should_refresh_within_interval(self, mock_db, refresh_config, known_people_dir):
        """Test should_refresh returns False when within interval."""
        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        # Add recent refresh record
        recent_time = datetime.now() - timedelta(days=30)
        conn = mock_db._get_conn()
        conn.execute(
            "INSERT INTO known_refresh_history(person_name, source_file_path, target_file_path, "
            "match_score, target_score, created_ts) VALUES(?,?,?,?,?,?)",
            ("Alice", "/test/src.jpg", "/known/alice/r.jpg", 0.65, 0.65, recent_time.isoformat()),
        )
        conn.commit()

        result = manager.should_refresh()

        assert result is False

    def test_should_refresh_after_interval(self, mock_db, refresh_config, known_people_dir):
        """Test should_refresh returns True after interval passes."""
        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        # Add old refresh record
        old_time = datetime.now() - timedelta(days=61)
        conn = mock_db._get_conn()
        conn.execute(
            "INSERT INTO known_refresh_history(person_name, source_file_path, target_file_path, "
            "match_score, target_score, created_ts) VALUES(?,?,?,?,?,?)",
            ("Alice", "/test/src.jpg", "/known/alice/r.jpg", 0.65, 0.65, old_time.isoformat()),
        )
        conn.commit()

        result = manager.should_refresh()

        assert result is True

    def test_find_candidates(self, mock_db, refresh_config, known_people_dir):
        """Test finding refresh candidates."""
        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        # Add some files to database
        mock_db.add_file_with_score("/test/img1.jpg", "hash1", 1, 1, 0.60, "Alice")
        mock_db.add_file_with_score("/test/img2.jpg", "hash2", 1, 1, 0.65, "Alice")
        mock_db.add_file_with_score("/test/img3.jpg", "hash3", 1, 1, 0.70, "Alice")

        # Find candidates
        candidates = manager.find_candidates("Alice")

        assert len(candidates) == 3
        # Should be sorted by score_delta (closest to target_score=0.65 first)
        assert candidates[0].source_path == "/test/img2.jpg"
        assert candidates[0].score_delta == 0.0
        assert abs(candidates[1].score_delta - 0.05) < 0.01  # Float comparison
        assert abs(candidates[2].score_delta - 0.05) < 0.01  # Float comparison

    def test_find_candidates_no_candidates(self, mock_db, refresh_config, known_people_dir):
        """Test finding candidates when none exist."""
        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        # No files in database
        candidates = manager.find_candidates("Alice")

        assert len(candidates) == 0

    @patch("dmaf.known_refresh.Image.open")
    @patch("dmaf.face_recognition.insightface_backend.get_face_bbox")
    @patch("dmaf.known_refresh.np.array")
    def test_crop_face_success(
        self,
        mock_np_array,
        mock_get_bbox,
        mock_image_open,
        mock_db,
        refresh_config,
        known_people_dir,
    ):
        """Test successful face cropping."""
        # Mock image
        mock_img = Mock(spec=Image.Image)
        mock_img.width = 1000
        mock_img.height = 1000
        mock_img.convert.return_value = mock_img
        mock_img.crop.return_value = mock_img
        mock_image_open.return_value = mock_img

        # Mock numpy array
        mock_np_array.return_value = np.zeros((1000, 1000, 3), dtype=np.uint8)

        # Mock face bbox (x1, y1, x2, y2)
        mock_get_bbox.return_value = (100, 100, 300, 300)

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        result = manager.crop_face("/test/img.jpg", padding_percent=0.3)

        assert result is not None
        mock_img.crop.assert_called_once()

        # Verify padding was applied
        crop_args = mock_img.crop.call_args[0][0]
        # bbox width = 200, padding = 60, so x1_padded = 40, x2_padded = 360
        assert crop_args[0] == 40  # x1_padded = max(0, 100 - 60)
        assert crop_args[1] == 40  # y1_padded = max(0, 100 - 60)
        assert crop_args[2] == 360  # x2_padded = min(1000, 300 + 60)
        assert crop_args[3] == 360  # y2_padded = min(1000, 300 + 60)

    @patch("dmaf.known_refresh.Image.open")
    @patch("dmaf.face_recognition.insightface_backend.get_face_bbox")
    def test_crop_face_no_face_detected(
        self, mock_get_bbox, mock_image_open, mock_db, refresh_config, known_people_dir
    ):
        """Test cropping when no face is detected."""
        # Mock image
        mock_img = Mock(spec=Image.Image)
        mock_img.convert.return_value = mock_img
        mock_image_open.return_value = mock_img

        # No face detected
        mock_get_bbox.return_value = None

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        result = manager.crop_face("/test/img.jpg")

        assert result is None

    @patch("dmaf.known_refresh.Image.open")
    def test_crop_face_image_load_error(
        self, mock_image_open, mock_db, refresh_config, known_people_dir
    ):
        """Test handling image load error."""
        mock_image_open.side_effect = Exception("Cannot open image")

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        result = manager.crop_face("/test/img.jpg")

        assert result is None

    def test_crop_face_dlib_backend_not_supported(self, mock_db, known_people_dir):
        """Test that dlib backend returns None for cropping."""
        config = KnownRefreshSettings(enabled=True)
        manager = KnownRefreshManager(config, mock_db, known_people_dir, "face_recognition")

        result = manager.crop_face("/test/img.jpg")

        assert result is None

    @patch("dmaf.known_refresh.KnownRefreshManager.crop_face")
    @patch("dmaf.known_refresh.KnownRefreshManager.find_candidates")
    @patch("dmaf.known_refresh.KnownRefreshManager.should_refresh")
    def test_run_refresh_success(
        self,
        mock_should_refresh,
        mock_find_candidates,
        mock_crop_face,
        mock_db,
        refresh_config,
        known_people_dir,
    ):
        """Test successful refresh run."""
        mock_should_refresh.return_value = True

        # Mock candidates for each person
        mock_find_candidates.side_effect = [
            [
                RefreshCandidate("Alice", "/test/alice1.jpg", 0.67, 0.02),
            ],
            [
                RefreshCandidate("Bob", "/test/bob1.jpg", 0.64, 0.01),
            ],
        ]

        # Mock cropped images
        mock_cropped_img = Mock(spec=Image.Image)
        mock_crop_face.return_value = mock_cropped_img

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        results = manager.run_refresh()

        assert len(results) == 2
        # Results can be in any order (depends on directory iteration)
        person_names = {r.person_name for r in results}
        assert person_names == {"Alice", "Bob"}

        # Verify images were saved
        assert mock_cropped_img.save.call_count == 2

        # Verify records were added to database
        conn = mock_db._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM known_refresh_history")
        assert cursor.fetchone()[0] == 2

    @patch("dmaf.known_refresh.KnownRefreshManager.should_refresh")
    def test_run_refresh_not_due(
        self, mock_should_refresh, mock_db, refresh_config, known_people_dir
    ):
        """Test run_refresh returns empty when not due."""
        mock_should_refresh.return_value = False

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        results = manager.run_refresh()

        assert len(results) == 0

    @patch("dmaf.known_refresh.KnownRefreshManager.crop_face")
    @patch("dmaf.known_refresh.KnownRefreshManager.find_candidates")
    @patch("dmaf.known_refresh.KnownRefreshManager.should_refresh")
    def test_run_refresh_no_candidates(
        self,
        mock_should_refresh,
        mock_find_candidates,
        mock_crop_face,
        mock_db,
        refresh_config,
        known_people_dir,
    ):
        """Test refresh when no candidates found."""
        mock_should_refresh.return_value = True
        mock_find_candidates.return_value = []

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        results = manager.run_refresh()

        assert len(results) == 0

    @patch("dmaf.known_refresh.KnownRefreshManager.crop_face")
    @patch("dmaf.known_refresh.KnownRefreshManager.find_candidates")
    @patch("dmaf.known_refresh.KnownRefreshManager.should_refresh")
    def test_run_refresh_crop_failure(
        self,
        mock_should_refresh,
        mock_find_candidates,
        mock_crop_face,
        mock_db,
        refresh_config,
        known_people_dir,
    ):
        """Test refresh when face cropping fails."""
        mock_should_refresh.return_value = True
        mock_find_candidates.side_effect = [
            [RefreshCandidate("Alice", "/test/alice1.jpg", 0.67, 0.02)],
            [],  # Bob has no candidates
        ]
        mock_crop_face.return_value = None  # Crop failed

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        results = manager.run_refresh()

        # Should handle failure gracefully
        assert len(results) == 0

    @patch("dmaf.known_refresh.KnownRefreshManager.crop_face")
    @patch("dmaf.known_refresh.KnownRefreshManager.find_candidates")
    @patch("dmaf.known_refresh.KnownRefreshManager.should_refresh")
    def test_run_refresh_save_failure(
        self,
        mock_should_refresh,
        mock_find_candidates,
        mock_crop_face,
        mock_db,
        refresh_config,
        known_people_dir,
    ):
        """Test refresh when image save fails."""
        mock_should_refresh.return_value = True
        mock_find_candidates.side_effect = [
            [RefreshCandidate("Alice", "/test/alice1.jpg", 0.67, 0.02)],
            [],  # Bob has no candidates
        ]

        # Mock cropped image that fails to save
        mock_cropped_img = Mock(spec=Image.Image)
        mock_cropped_img.save.side_effect = Exception("Save failed")
        mock_crop_face.return_value = mock_cropped_img

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        results = manager.run_refresh()

        # Should handle failure gracefully
        assert len(results) == 0

    def test_run_refresh_known_dir_not_exists(self, mock_db, refresh_config, temp_dir):
        """Test refresh when known_people directory doesn't exist."""
        nonexistent_dir = temp_dir / "nonexistent"

        manager = KnownRefreshManager(refresh_config, mock_db, nonexistent_dir, "insightface")

        results = manager.run_refresh()

        assert len(results) == 0

    @patch("dmaf.known_refresh.KnownRefreshManager.crop_face")
    @patch("dmaf.known_refresh.KnownRefreshManager.find_candidates")
    @patch("dmaf.known_refresh.KnownRefreshManager.should_refresh")
    def test_run_refresh_target_filename_format(
        self,
        mock_should_refresh,
        mock_find_candidates,
        mock_crop_face,
        mock_db,
        refresh_config,
        known_people_dir,
    ):
        """Test that refresh creates correctly formatted filenames."""
        mock_should_refresh.return_value = True
        mock_find_candidates.side_effect = [
            [RefreshCandidate("Alice", "/test/alice1.jpg", 0.67, 0.02)],
            [],  # Bob has no candidates
        ]

        mock_cropped_img = Mock(spec=Image.Image)
        mock_crop_face.return_value = mock_cropped_img

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        results = manager.run_refresh()

        assert len(results) == 1

        # Check filename format: refresh_YYYYMMDD_HHMMSS_0.67.jpg
        target_path = results[0].target_file_path
        filename = Path(target_path).name

        assert filename.startswith("refresh_")
        assert filename.endswith("_0.67.jpg")
        # Should contain timestamp in format YYYYMMDD_HHMMSS
        parts = filename.split("_")
        assert len(parts) == 4  # ["refresh", "YYYYMMDD", "HHMMSS", "0.67.jpg"]

    @patch("dmaf.known_refresh.Image.open")
    @patch("dmaf.face_recognition.insightface_backend.get_face_bbox")
    @patch("dmaf.known_refresh.np.array")
    def test_crop_face_respects_image_boundaries(
        self,
        mock_np_array,
        mock_get_bbox,
        mock_image_open,
        mock_db,
        refresh_config,
        known_people_dir,
    ):
        """Test that cropping respects image boundaries."""
        # Mock small image
        mock_img = Mock(spec=Image.Image)
        mock_img.width = 100
        mock_img.height = 100
        mock_img.convert.return_value = mock_img
        mock_img.crop.return_value = mock_img
        mock_image_open.return_value = mock_img

        # Mock numpy array
        mock_np_array.return_value = np.zeros((100, 100, 3), dtype=np.uint8)

        # Face bbox near edge
        mock_get_bbox.return_value = (10, 10, 50, 50)

        manager = KnownRefreshManager(refresh_config, mock_db, known_people_dir, "insightface")

        result = manager.crop_face("/test/img.jpg", padding_percent=0.5)

        assert result is not None

        # Verify padding doesn't go out of bounds
        crop_args = mock_img.crop.call_args[0][0]
        assert crop_args[0] >= 0
        assert crop_args[1] >= 0
        assert crop_args[2] <= 100
        assert crop_args[3] <= 100
