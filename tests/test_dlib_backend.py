"""Basic tests for dlib face recognition backend."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest

from wa_automate.face_recognition import dlib_backend


class TestLoadKnownFaces:
    """Test load_known_faces function."""

    @patch('wa_automate.face_recognition.dlib_backend.face_recognition')
    def test_load_known_faces_empty_directory(self, mock_fr, temp_dir: Path):
        """Test loading from empty directory."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        encodings_dict, people_list = dlib_backend.load_known_faces(str(known_dir))

        assert encodings_dict == {}
        assert people_list == []

    @patch('wa_automate.face_recognition.dlib_backend.face_recognition')
    def test_load_known_faces_with_person(self, mock_fr, temp_dir: Path):
        """Test loading faces for one person."""
        # Setup directory structure
        known_dir = temp_dir / "known_people"
        alice_dir = known_dir / "alice"
        alice_dir.mkdir(parents=True)

        # Create fake image
        image1 = alice_dir / "photo1.jpg"
        image1.write_bytes(b"fake_image_data")

        # Mock face_recognition functions
        mock_fr.load_image_file.return_value = np.zeros((100, 100, 3))
        mock_fr.face_encodings.return_value = [np.array([1, 2, 3])]

        encodings_dict, people_list = dlib_backend.load_known_faces(str(known_dir))

        assert "alice" in encodings_dict
        assert len(encodings_dict["alice"]) == 1
        assert people_list == ["alice"]

    @patch('wa_automate.face_recognition.dlib_backend.face_recognition')
    def test_load_known_faces_skips_zone_identifier(self, mock_fr, temp_dir: Path):
        """Test that Zone.Identifier files are skipped."""
        known_dir = temp_dir / "known_people"
        bob_dir = known_dir / "bob"
        bob_dir.mkdir(parents=True)

        # Create regular image and Zone.Identifier file
        image1 = bob_dir / "photo1.jpg"
        image1.write_bytes(b"fake_image")

        zone_file = bob_dir / "photo1.jpg:Zone.Identifier"
        zone_file.write_text("[ZoneTransfer]\nZoneId=3")

        mock_fr.load_image_file.return_value = np.zeros((100, 100, 3))
        mock_fr.face_encodings.return_value = [np.array([4, 5, 6])]

        dlib_backend.load_known_faces(str(known_dir))

        # Should only load the image, not the Zone.Identifier file
        assert mock_fr.load_image_file.call_count == 1

    @patch('wa_automate.face_recognition.dlib_backend.face_recognition')
    def test_load_known_faces_multiple_people(self, mock_fr, temp_dir: Path):
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

        mock_fr.load_image_file.return_value = np.zeros((100, 100, 3))
        mock_fr.face_encodings.side_effect = [
            [np.array([1, 2, 3])],  # Alice
            [np.array([4, 5, 6])]   # Bob
        ]

        encodings_dict, people_list = dlib_backend.load_known_faces(str(known_dir))

        assert len(encodings_dict) == 2
        assert "alice" in encodings_dict
        assert "bob" in encodings_dict
        assert set(people_list) == {"alice", "bob"}


class TestBestMatch:
    """Test best_match function."""

    @patch('wa_automate.face_recognition.dlib_backend.face_recognition')
    def test_best_match_no_faces(self, mock_fr):
        """Test matching when no faces detected in image."""
        known = {"alice": [np.array([1, 2, 3])]}
        img = np.zeros((100, 100, 3), dtype=np.uint8)

        mock_fr.face_locations.return_value = []  # No faces detected

        matched, names = dlib_backend.best_match(known, img, tolerance=0.5)

        assert matched is False
        assert names == []

    @patch('wa_automate.face_recognition.dlib_backend.face_recognition')
    def test_best_match_found(self, mock_fr):
        """Test successful face match."""
        known_encoding = np.array([1, 2, 3])
        known = {"alice": [known_encoding]}
        img = np.zeros((100, 100, 3), dtype=np.uint8)

        # Mock face location detection (returns top, right, bottom, left)
        mock_fr.face_locations.return_value = [(0, 100, 100, 0)]  # 100x100 face

        # Mock face encoding extraction
        mock_fr.face_encodings.return_value = [np.array([1.1, 2.1, 3.1])]

        # Mock face comparison
        mock_fr.compare_faces.return_value = [True]

        matched, names = dlib_backend.best_match(known, img, tolerance=0.5)

        assert matched is True
        assert "alice" in names

    @patch('wa_automate.face_recognition.dlib_backend.face_recognition')
    def test_best_match_not_found(self, mock_fr):
        """Test when face doesn't match any known person."""
        known = {"alice": [np.array([1, 2, 3])]}
        img = np.zeros((100, 100, 3), dtype=np.uint8)

        mock_fr.face_locations.return_value = [(0, 100, 100, 0)]
        mock_fr.face_encodings.return_value = [np.array([7, 8, 9])]
        mock_fr.compare_faces.return_value = [False]

        matched, names = dlib_backend.best_match(known, img, tolerance=0.5)

        assert matched is False
        assert names == []
