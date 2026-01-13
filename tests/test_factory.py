"""Tests for face recognition backend factory."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from wa_automate.face_recognition import factory


class TestGetBackend:
    """Test _get_backend function."""

    def setup_method(self):
        """Clear backend cache before each test."""
        factory._backend_cache.clear()

    def test_get_face_recognition_backend(self):
        """Test loading face_recognition backend."""
        with patch.dict("sys.modules", {"wa_automate.face_recognition.dlib_backend": MagicMock()}):
            backend = factory._get_backend("face_recognition")
            assert backend is not None
            assert "face_recognition" in factory._backend_cache

    def test_get_insightface_backend(self):
        """Test loading insightface backend."""
        with patch.dict(
            "sys.modules", {"wa_automate.face_recognition.insightface_backend": MagicMock()}
        ):
            backend = factory._get_backend("insightface")
            assert backend is not None
            assert "insightface" in factory._backend_cache

    def test_invalid_backend_raises_error(self):
        """Test that invalid backend name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown backend: invalid"):
            factory._get_backend("invalid")

        with pytest.raises(ValueError, match="Supported backends"):
            factory._get_backend("some_other_backend")

    def test_backend_caching(self):
        """Test that backends are cached after first load."""
        mock_backend = MagicMock()

        with patch.dict("sys.modules", {"wa_automate.face_recognition.dlib_backend": mock_backend}):
            # First call loads backend
            backend1 = factory._get_backend("face_recognition")

            # Second call should return cached backend
            backend2 = factory._get_backend("face_recognition")

            # Should be the same object
            assert backend1 is backend2


class TestLoadKnownFaces:
    """Test load_known_faces function."""

    def setup_method(self):
        """Clear backend cache before each test."""
        factory._backend_cache.clear()

    def test_load_with_face_recognition_backend(self):
        """Test loading known faces with face_recognition backend."""
        # Mock backend
        mock_backend = MagicMock()
        mock_encodings = {"alice": [np.array([1, 2, 3])]}
        mock_people = ["alice"]
        mock_backend.load_known_faces.return_value = (mock_encodings, mock_people)

        with patch("wa_automate.face_recognition.factory._get_backend", return_value=mock_backend):
            encodings, people = factory.load_known_faces(
                "/path/to/known_people", backend_name="face_recognition"
            )

            # Verify backend was called correctly
            mock_backend.load_known_faces.assert_called_once_with("/path/to/known_people")

            # Verify results
            assert encodings == mock_encodings
            assert people == mock_people

    def test_load_with_insightface_backend(self):
        """Test loading known faces with insightface backend."""
        # Mock backend
        mock_backend = MagicMock()
        mock_encodings = {"bob": [np.array([4, 5, 6])]}
        mock_people = ["bob"]
        mock_backend.load_known_faces.return_value = (mock_encodings, mock_people)

        with patch("wa_automate.face_recognition.factory._get_backend", return_value=mock_backend):
            encodings, people = factory.load_known_faces(
                "/path/to/known_people", backend_name="insightface", min_face_size=100
            )

            # InsightFace backend gets min_face_size and enable_augmentation parameters
            mock_backend.load_known_faces.assert_called_once_with(
                "/path/to/known_people", 100, True
            )

            assert encodings == mock_encodings
            assert people == mock_people

    def test_load_default_backend(self):
        """Test that default backend is face_recognition."""
        mock_backend = MagicMock()
        mock_backend.load_known_faces.return_value = ({}, [])

        with patch(
            "wa_automate.face_recognition.factory._get_backend", return_value=mock_backend
        ) as mock_get:
            factory.load_known_faces("/path/to/known_people")

            # Should use face_recognition as default
            mock_get.assert_called_with("face_recognition")

    def test_load_with_min_face_size_face_recognition(self):
        """Test that min_face_size is not passed to face_recognition backend."""
        mock_backend = MagicMock()
        mock_backend.load_known_faces.return_value = ({}, [])

        with patch("wa_automate.face_recognition.factory._get_backend", return_value=mock_backend):
            # min_face_size is provided but shouldn't be passed to face_recognition
            factory.load_known_faces(
                "/path/to/known_people", backend_name="face_recognition", min_face_size=50
            )

            # face_recognition backend only gets the path
            mock_backend.load_known_faces.assert_called_once_with("/path/to/known_people")


class TestBestMatch:
    """Test best_match function."""

    def setup_method(self):
        """Clear backend cache before each test."""
        factory._backend_cache.clear()

    def test_best_match_with_face_recognition(self):
        """Test best_match with face_recognition backend."""
        # Mock backend
        mock_backend = MagicMock()
        mock_backend.best_match.return_value = (True, ["alice"])

        known_faces = {"alice": [np.array([1, 2, 3])]}
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)

        with patch("wa_automate.face_recognition.factory._get_backend", return_value=mock_backend):
            matched, names = factory.best_match(
                known_faces,
                test_image,
                backend_name="face_recognition",
                tolerance=0.5,
                min_face_size=80,
            )

            # Verify backend was called with correct parameters
            mock_backend.best_match.assert_called_once()
            call_args = mock_backend.best_match.call_args

            assert call_args[0][0] == known_faces  # known
            assert np.array_equal(call_args[0][1], test_image)  # img_rgb
            assert call_args[1]["tolerance"] == 0.5
            assert call_args[1]["min_face_size"] == 80

            # Verify results
            assert matched is True
            assert names == ["alice"]

    def test_best_match_with_insightface(self):
        """Test best_match with insightface backend."""
        mock_backend = MagicMock()
        mock_backend.best_match.return_value = (True, ["bob", "charlie"])

        known_faces = {"bob": [np.array([1, 2, 3])], "charlie": [np.array([4, 5, 6])]}
        test_image = np.zeros((200, 200, 3), dtype=np.uint8)

        with patch("wa_automate.face_recognition.factory._get_backend", return_value=mock_backend):
            matched, names = factory.best_match(
                known_faces,
                test_image,
                backend_name="insightface",
                tolerance=0.4,
                min_face_size=100,
            )

            assert matched is True
            assert names == ["bob", "charlie"]

    def test_best_match_no_match(self):
        """Test best_match when no faces match."""
        mock_backend = MagicMock()
        mock_backend.best_match.return_value = (False, [])

        known_faces = {"alice": [np.array([1, 2, 3])]}
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)

        with patch("wa_automate.face_recognition.factory._get_backend", return_value=mock_backend):
            matched, names = factory.best_match(
                known_faces, test_image, backend_name="face_recognition"
            )

            assert matched is False
            assert names == []

    def test_best_match_default_parameters(self):
        """Test best_match with default parameters."""
        mock_backend = MagicMock()
        mock_backend.best_match.return_value = (False, [])

        with patch(
            "wa_automate.face_recognition.factory._get_backend", return_value=mock_backend
        ) as mock_get:
            factory.best_match({}, np.zeros((100, 100, 3), dtype=np.uint8))

            # Should use face_recognition as default
            mock_get.assert_called_with("face_recognition")

            # Check default tolerance and min_face_size were passed
            call_kwargs = mock_backend.best_match.call_args[1]
            assert call_kwargs["tolerance"] == 0.52
            assert call_kwargs["min_face_size"] == 80

    def test_best_match_custom_tolerance(self):
        """Test best_match with custom tolerance."""
        mock_backend = MagicMock()
        mock_backend.best_match.return_value = (False, [])

        with patch("wa_automate.face_recognition.factory._get_backend", return_value=mock_backend):
            factory.best_match({}, np.zeros((100, 100, 3), dtype=np.uint8), tolerance=0.3)

            call_kwargs = mock_backend.best_match.call_args[1]
            assert call_kwargs["tolerance"] == 0.3


class TestFactoryIntegration:
    """Test integration between factory functions."""

    def setup_method(self):
        """Clear backend cache before each test."""
        factory._backend_cache.clear()

    def test_backend_reused_across_functions(self):
        """Test that backend is cached and reused across load_known_faces and best_match."""
        mock_backend = MagicMock()
        mock_backend.load_known_faces.return_value = ({"alice": []}, ["alice"])
        mock_backend.best_match.return_value = (True, ["alice"])

        with patch(
            "wa_automate.face_recognition.factory._get_backend", return_value=mock_backend
        ) as mock_get:
            # Call load_known_faces
            factory.load_known_faces("/path", backend_name="face_recognition")

            # Call best_match
            factory.best_match({}, np.zeros((10, 10, 3)), backend_name="face_recognition")

            # _get_backend should have been called twice (once per function call)
            assert mock_get.call_count == 2

            # But both times should have used the cache (mock_get returns same object)
            assert all(call[0][0] == "face_recognition" for call in mock_get.call_args_list)

    def test_different_backends_cached_separately(self):
        """Test that different backends are cached separately."""
        mock_dlib = MagicMock()
        mock_insightface = MagicMock()

        def get_backend_side_effect(name):
            if name == "face_recognition":
                return mock_dlib
            return mock_insightface

        mock_dlib.best_match.return_value = (False, [])
        mock_insightface.best_match.return_value = (False, [])

        with patch(
            "wa_automate.face_recognition.factory._get_backend", side_effect=get_backend_side_effect
        ):
            # Use both backends
            factory.best_match({}, np.zeros((10, 10, 3)), backend_name="face_recognition")
            factory.best_match({}, np.zeros((10, 10, 3)), backend_name="insightface")

            # Both backends should have been called
            mock_dlib.best_match.assert_called_once()
            mock_insightface.best_match.assert_called_once()
