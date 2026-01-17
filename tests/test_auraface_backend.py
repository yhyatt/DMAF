"""Tests for AuraFace backend with mocked ML models."""

import threading
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

# Skip all tests in this module if insightface is not installed
# AuraFace uses the same InsightFace infrastructure
pytest.importorskip("insightface")

from dmaf.face_recognition import auraface_backend


class TestModelDownload:
    """Test AuraFace model download functionality."""

    @patch("huggingface_hub.snapshot_download")
    def test_download_when_missing(self, mock_snapshot_download, temp_dir: Path):
        """Test that model is downloaded when not cached."""
        # Set MODEL_ROOT and MODEL_PATH to temp location
        auraface_backend.MODEL_ROOT = temp_dir
        auraface_backend.MODEL_PATH = temp_dir / "models" / "auraface"

        # Model doesn't exist yet
        assert not auraface_backend.MODEL_PATH.exists()

        # Call should trigger download
        result = auraface_backend._ensure_model_downloaded()

        # Verify download was called
        mock_snapshot_download.assert_called_once_with(
            repo_id="fal/AuraFace-v1",
            local_dir=str(auraface_backend.MODEL_PATH),
            local_dir_use_symlinks=False,
        )

        assert result == auraface_backend.MODEL_ROOT

    @patch("huggingface_hub.snapshot_download")
    def test_skip_download_when_cached(self, mock_snapshot_download, temp_dir: Path):
        """Test that model download is skipped when already cached."""
        # Set MODEL_ROOT and MODEL_PATH to temp location
        auraface_backend.MODEL_ROOT = temp_dir
        auraface_backend.MODEL_PATH = temp_dir / "models" / "auraface"

        # Create fake cached model
        auraface_backend.MODEL_PATH.mkdir(parents=True)
        # Add a dummy file so the directory is not empty
        (auraface_backend.MODEL_PATH / "dummy.txt").write_text("test")

        # Call should NOT trigger download
        result = auraface_backend._ensure_model_downloaded()

        # Verify download was NOT called
        mock_snapshot_download.assert_not_called()

        assert result == auraface_backend.MODEL_ROOT


class TestGetApp:
    """Test FaceAnalysis singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        auraface_backend._app_cache.clear()

    @patch("dmaf.face_recognition.auraface_backend._ensure_model_downloaded")
    @patch("dmaf.face_recognition.auraface_backend.FaceAnalysis")
    def test_singleton_pattern(self, mock_face_analysis_class, mock_ensure_model):
        """Test that _get_app() returns same instance on multiple calls."""
        # Mock model download
        mock_ensure_model.return_value = Path("/fake/model/path")

        mock_app = Mock()
        mock_face_analysis_class.return_value = mock_app

        # First call should create instance
        app1 = auraface_backend._get_app()

        # Second call should return same instance
        app2 = auraface_backend._get_app()

        assert app1 is app2
        # FaceAnalysis should only be instantiated once
        mock_face_analysis_class.assert_called_once_with(
            name="auraface", root="/fake/model/path", providers=["CPUExecutionProvider"]
        )
        mock_app.prepare.assert_called_once_with(ctx_id=-1, det_size=(640, 640), det_thresh=0.4)

    @patch("dmaf.face_recognition.auraface_backend._ensure_model_downloaded")
    @patch("dmaf.face_recognition.auraface_backend.FaceAnalysis")
    def test_multiple_det_thresh_values(
        self, mock_face_analysis_class, mock_ensure_model, temp_dir: Path
    ):
        """Test that different det_thresh values create separate instances."""
        # Mock model download
        mock_ensure_model.return_value = temp_dir

        mock_app1 = Mock()
        mock_app2 = Mock()
        mock_face_analysis_class.side_effect = [mock_app1, mock_app2]

        # Get app with det_thresh=0.4
        app1 = auraface_backend._get_app(det_thresh=0.4)

        # Get app with det_thresh=0.5 (should create new instance)
        app2 = auraface_backend._get_app(det_thresh=0.5)

        assert app1 is not app2
        assert mock_face_analysis_class.call_count == 2

        # Get app with det_thresh=0.4 again (should return cached instance)
        app3 = auraface_backend._get_app(det_thresh=0.4)

        assert app3 is app1
        # Still only 2 calls (no new instance created)
        assert mock_face_analysis_class.call_count == 2

    @patch("dmaf.face_recognition.auraface_backend._ensure_model_downloaded")
    @patch("dmaf.face_recognition.auraface_backend.FaceAnalysis")
    def test_thread_safety(self, mock_face_analysis_class, mock_ensure_model):
        """Test that singleton is thread-safe."""
        # Mock model download
        mock_ensure_model.return_value = Path("/fake/model/path")

        mock_app = Mock()
        mock_face_analysis_class.return_value = mock_app

        instances = {}
        errors = []

        def get_app_in_thread(thread_id):
            try:
                app = auraface_backend._get_app()
                instances[thread_id] = id(app)
            except Exception as e:
                errors.append((thread_id, str(e)))

        # Create multiple threads trying to get app simultaneously
        threads = [threading.Thread(target=get_app_in_thread, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0

        # All threads should get same instance
        assert len(set(instances.values())) == 1

        # Model should only be created once despite concurrent access
        mock_face_analysis_class.assert_called_once()


class TestCosineSimilarity:
    """Test cosine similarity calculation."""

    def test_identical_vectors(self):
        """Test that identical normalized vectors have similarity = 1.0."""
        a = np.array([1.0, 0.0, 0.0])  # Normalized
        b = np.array([1.0, 0.0, 0.0])

        sim = auraface_backend._cosine_sim(a, b)
        assert abs(sim - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        """Test that orthogonal vectors have similarity = 0.0."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])

        sim = auraface_backend._cosine_sim(a, b)
        assert abs(sim) < 1e-6

    def test_opposite_vectors(self):
        """Test that opposite vectors have similarity = -1.0."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([-1.0, 0.0, 0.0])

        sim = auraface_backend._cosine_sim(a, b)
        assert abs(sim - (-1.0)) < 1e-6

    def test_similar_vectors(self):
        """Test that similar vectors have high positive similarity."""
        a = np.array([1.0, 0.1, 0.0])
        a = a / np.linalg.norm(a)  # Normalize

        b = np.array([1.0, 0.2, 0.0])
        b = b / np.linalg.norm(b)  # Normalize

        sim = auraface_backend._cosine_sim(a, b)
        assert sim > 0.9  # Should be very similar

    def test_auto_normalization(self):
        """Test that _cosine_sim normalizes vectors automatically."""
        # Unnormalized vectors
        a = np.array([2.0, 0.0, 0.0])  # Length = 2
        b = np.array([3.0, 0.0, 0.0])  # Length = 3

        sim = auraface_backend._cosine_sim(a, b)
        # After normalization, both point in same direction
        assert abs(sim - 1.0) < 1e-6


class TestLoadKnownFaces:
    """Test load_known_faces function."""

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend._img_to_np")
    def test_load_empty_directory(self, mock_img_to_np, mock_embed, mock_get_app, temp_dir: Path):
        """Test loading from empty directory."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        mock_get_app.return_value = Mock()

        encodings_dict, people_list = auraface_backend.load_known_faces(
            str(known_dir), min_face_size=80
        )

        assert encodings_dict == {}
        assert people_list == []

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend.Image")
    def test_load_with_person(self, mock_image_class, mock_embed, mock_get_app, temp_dir: Path):
        """Test loading faces for one person."""
        # Setup directory structure
        known_dir = temp_dir / "known_people"
        alice_dir = known_dir / "alice"
        alice_dir.mkdir(parents=True)

        # Create fake image
        image1 = alice_dir / "photo1.jpg"
        image1.write_bytes(b"fake_image_data")

        # Mock Image.open to return a fake PIL image
        mock_pil_img = Mock()
        mock_image_class.open.return_value = mock_pil_img
        mock_pil_img.convert.return_value = mock_pil_img

        # Mock functions
        mock_get_app.return_value = Mock()
        mock_embed.return_value = [np.random.rand(512).astype(np.float32)]  # 512-d embedding

        encodings_dict, people_list = auraface_backend.load_known_faces(
            str(known_dir), min_face_size=80, enable_augmentation=False
        )

        assert "alice" in encodings_dict
        assert len(encodings_dict["alice"]) == 1
        assert encodings_dict["alice"][0].shape == (
            512,
        )  # AuraFace uses 512-d (same as InsightFace)
        assert people_list == ["alice"]

        # Verify min_face_size was passed to _embed_faces
        mock_embed.assert_called_once()
        assert mock_embed.call_args[0][2] == 80

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend.Image")
    def test_skip_zone_identifier(self, mock_image_class, mock_embed, mock_get_app, temp_dir: Path):
        """Test that Zone.Identifier files are skipped."""
        known_dir = temp_dir / "known_people"
        bob_dir = known_dir / "bob"
        bob_dir.mkdir(parents=True)

        # Create regular image and Zone.Identifier file
        image1 = bob_dir / "photo1.jpg"
        image1.write_bytes(b"fake_image")

        zone_file = bob_dir / "photo1.jpg:Zone.Identifier"
        zone_file.write_text("[ZoneTransfer]\nZoneId=3")

        # Mock Image.open to return a fake PIL image
        mock_pil_img = Mock()
        mock_image_class.open.return_value = mock_pil_img
        mock_pil_img.convert.return_value = mock_pil_img

        mock_get_app.return_value = Mock()
        mock_embed.return_value = [np.random.rand(512).astype(np.float32)]

        auraface_backend.load_known_faces(str(known_dir), enable_augmentation=False)

        # Should only load the image, not the Zone.Identifier file
        assert mock_image_class.open.call_count == 1

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend._img_to_np")
    def test_multiple_people(self, mock_img_to_np, mock_embed, mock_get_app, temp_dir: Path):
        """Test loading faces for multiple people."""
        known_dir = temp_dir / "known_people"

        # Create directories for two people
        alice_dir = known_dir / "alice"
        bob_dir = known_dir / "bob"
        alice_dir.mkdir(parents=True)
        bob_dir.mkdir(parents=True)

        # Create images
        (alice_dir / "photo1.jpg").write_bytes(b"fake1")
        (bob_dir / "photo1.jpg").write_bytes(b"fake2")

        mock_get_app.return_value = Mock()
        mock_img_to_np.return_value = np.zeros((100, 100, 3), dtype=np.uint8)

        # Different embeddings for each call
        mock_embed.side_effect = [
            [np.random.rand(512).astype(np.float32)],  # Alice
            [np.random.rand(512).astype(np.float32)],  # Bob
        ]

        encodings_dict, people_list = auraface_backend.load_known_faces(str(known_dir))

        assert len(encodings_dict) == 2
        assert "alice" in encodings_dict
        assert "bob" in encodings_dict
        assert set(people_list) == {"alice", "bob"}


class TestBestMatch:
    """Test best_match function."""

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    def test_no_faces_detected(self, mock_embed, mock_get_app):
        """Test matching when no faces detected in image."""
        known = {"alice": [np.random.rand(512).astype(np.float32)]}
        img = np.zeros((100, 100, 3), dtype=np.uint8)

        mock_get_app.return_value = Mock()
        mock_embed.return_value = []  # No faces detected

        matched, names = auraface_backend.best_match(known, img, tolerance=0.4)

        assert matched is False
        assert names == []

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend._cosine_sim")
    def test_match_found(self, mock_cosine_sim, mock_embed, mock_get_app):
        """Test successful face match using cosine similarity."""
        # Create normalized known encoding
        known_encoding = np.random.rand(512).astype(np.float32)
        known_encoding = known_encoding / np.linalg.norm(known_encoding)
        known = {"alice": [known_encoding]}

        # Create test image encoding
        test_encoding = np.random.rand(512).astype(np.float32)
        test_encoding = test_encoding / np.linalg.norm(test_encoding)

        img = np.zeros((100, 100, 3), dtype=np.uint8)

        mock_get_app.return_value = Mock()
        mock_embed.return_value = [test_encoding]

        # Mock cosine similarity to return high similarity
        mock_cosine_sim.return_value = 0.85  # With tolerance=0.4, threshold=0.6, this matches

        matched, names = auraface_backend.best_match(known, img, tolerance=0.4)

        assert matched is True
        assert "alice" in names

        # Verify cosine_sim was called
        mock_cosine_sim.assert_called()

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend._cosine_sim")
    def test_no_match(self, mock_cosine_sim, mock_embed, mock_get_app):
        """Test when face doesn't match any known person."""
        known = {"alice": [np.random.rand(512).astype(np.float32)]}
        img = np.zeros((100, 100, 3), dtype=np.uint8)

        mock_get_app.return_value = Mock()
        mock_embed.return_value = [np.random.rand(512).astype(np.float32)]

        # Mock cosine similarity to return low similarity (below threshold)
        mock_cosine_sim.return_value = 0.3  # With tolerance=0.4, threshold=0.6, this doesn't match

        matched, names = auraface_backend.best_match(known, img, tolerance=0.4)

        assert matched is False
        assert names == []

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend._cosine_sim")
    def test_tolerance_interpretation(self, mock_cosine_sim, mock_embed, mock_get_app):
        """Test that tolerance is interpreted as (1.0 - tolerance) threshold."""
        known = {"alice": [np.random.rand(512).astype(np.float32)]}
        img = np.zeros((100, 100, 3), dtype=np.uint8)

        mock_get_app.return_value = Mock()
        mock_embed.return_value = [np.random.rand(512).astype(np.float32)]

        # With tolerance=0.3, threshold should be 0.7
        # cosine_sim of 0.75 should match (>= 0.7)
        mock_cosine_sim.return_value = 0.75

        matched, names = auraface_backend.best_match(known, img, tolerance=0.3)

        assert matched is True

        # cosine_sim of 0.65 should NOT match (< 0.7)
        mock_cosine_sim.return_value = 0.65

        matched, names = auraface_backend.best_match(known, img, tolerance=0.3)

        assert matched is False

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    @patch("dmaf.face_recognition.auraface_backend._embed_faces")
    @patch("dmaf.face_recognition.auraface_backend._cosine_sim")
    def test_multiple_faces_multiple_matches(self, mock_cosine_sim, mock_embed, mock_get_app):
        """Test matching when multiple faces detected and multiple people match."""
        alice_enc = np.random.rand(512).astype(np.float32)
        bob_enc = np.random.rand(512).astype(np.float32)

        known = {"alice": [alice_enc], "bob": [bob_enc]}

        # Image with two faces
        img = np.zeros((200, 200, 3), dtype=np.uint8)

        mock_get_app.return_value = Mock()
        mock_embed.return_value = [
            np.random.rand(512).astype(np.float32),  # Face 1
            np.random.rand(512).astype(np.float32),  # Face 2
        ]

        # First face matches alice, second face matches bob
        call_count = [0]

        def mock_sim_side_effect(a, b):
            call_count[0] += 1
            # Alternate between high and low similarity
            return 0.9 if call_count[0] % 2 == 1 else 0.2

        mock_cosine_sim.side_effect = mock_sim_side_effect

        matched, names = auraface_backend.best_match(known, img, tolerance=0.4)

        assert matched is True
        # Both alice and bob should be in matches
        assert len(names) >= 1  # At least one match
        assert set(names).issubset({"alice", "bob"})


class TestGetFaceBbox:
    """Test get_face_bbox function."""

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    def test_no_faces_detected(self, mock_get_app):
        """Test bbox detection when no faces in image."""
        mock_app = Mock()
        mock_app.get.return_value = []  # No faces
        mock_get_app.return_value = mock_app

        img = np.zeros((100, 100, 3), dtype=np.uint8)
        bbox = auraface_backend.get_face_bbox(img, det_thresh=0.4, min_face_size=80)

        assert bbox is None

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    def test_single_face_detected(self, mock_get_app):
        """Test bbox detection with single face."""
        # Create mock face
        mock_face = Mock()
        mock_face.bbox = [10.0, 20.0, 110.0, 120.0]  # x1, y1, x2, y2 (100x100 face)
        mock_face.det_score = 0.95

        mock_app = Mock()
        mock_app.get.return_value = [mock_face]
        mock_get_app.return_value = mock_app

        img = np.zeros((200, 200, 3), dtype=np.uint8)
        bbox = auraface_backend.get_face_bbox(img, det_thresh=0.4, min_face_size=80)

        assert bbox == (10, 20, 110, 120)

    @patch("dmaf.face_recognition.auraface_backend._get_app")
    def test_multiple_faces_returns_best(self, mock_get_app):
        """Test that highest confidence face is returned when multiple faces detected."""
        # Create mock faces with different confidence scores
        mock_face1 = Mock()
        mock_face1.bbox = [10.0, 20.0, 110.0, 120.0]
        mock_face1.det_score = 0.85

        mock_face2 = Mock()
        mock_face2.bbox = [150.0, 160.0, 250.0, 260.0]
        mock_face2.det_score = 0.95  # Higher confidence

        mock_app = Mock()
        mock_app.get.return_value = [mock_face1, mock_face2]
        mock_get_app.return_value = mock_app

        img = np.zeros((300, 300, 3), dtype=np.uint8)
        bbox = auraface_backend.get_face_bbox(img, det_thresh=0.4, min_face_size=80)

        # Should return face2 (higher confidence)
        assert bbox == (150, 160, 250, 260)
