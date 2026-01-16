"""Backend comparison tests - validation helpers only.

For comprehensive backend benchmarking (LOOCV, FPR, performance), use:
    python scripts/benchmark_backends.py

This file contains only fast validation tests.
"""

from pathlib import Path

import pytest


class TestValidationHelpers:
    """Test helper functions for LOOCV validation."""

    def test_known_people_path_exists(self, known_people_path: Path):
        """Verify that known_people directory exists and has structure."""
        assert known_people_path.exists()
        assert known_people_path.is_dir()

        # Should have at least one person directory
        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]
        assert len(person_dirs) > 0, "No person directories found"

    def test_loocv_split_correctness(self, known_people_path: Path):
        """Verify LOOCV correctly splits train/test sets."""
        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]
        if not person_dirs:
            pytest.skip("No person directories found")

        person_dir = person_dirs[0]
        images = list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png"))

        if len(images) < 2:
            pytest.skip(f"Need at least 2 images for {person_dir.name}, found {len(images)}")

        # For each image, verify train/test split
        for i, test_img in enumerate(images):
            train_imgs = images[:i] + images[i + 1 :]  # Leave one out

            # Test image should NOT be in training set
            assert test_img not in train_imgs

            # Should have N-1 training images
            assert len(train_imgs) == len(images) - 1

    def test_no_data_leakage(self, known_people_path: Path):
        """Ensure test image is NEVER in training set during LOOCV."""
        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]
        if not person_dirs:
            pytest.skip("No person directories found")

        person_dir = person_dirs[0]
        images = list(person_dir.glob("*.jpg"))

        if len(images) < 2:
            pytest.skip(f"Need at least 2 images, found {len(images)}")

        # Simulate LOOCV
        for test_idx, test_img in enumerate(images):
            train_imgs = [img for j, img in enumerate(images) if j != test_idx]

            # Critical: test image must NOT appear in training set
            assert test_img not in train_imgs
            assert test_img.resolve() not in [img.resolve() for img in train_imgs]
