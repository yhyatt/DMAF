"""Backend comparison tests using Leave-One-Out Cross-Validation (LOOCV).

These tests use REAL images from data/known_people/ to compare accuracy and
performance between face_recognition (dlib) and insightface backends.

PRIVACY NOTE: These tests use personal family photos but do not expose or
commit their contents. Results stay local.
"""

import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaf.face_recognition import factory


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


class TestBackendAccuracy:
    """Compare accuracy between backends using LOOCV validation."""

    @pytest.mark.slow
    @pytest.mark.parametrize("backend_name", ["face_recognition", "insightface"])
    def test_same_person_loocv(self, known_people_path: Path, backend_name: str):
        """
        Leave-one-out cross-validation for same-person matching.

        For each person:
          For each image I:
            Train: Use all OTHER images as known encodings
            Test: Try to match image I
            Record: Did it correctly identify the person?
        """
        results = {"correct": 0, "incorrect": 0, "total": 0}

        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]

        print(f"\n{'=' * 60}")
        print(f"Starting LOOCV for {backend_name} backend")
        print(f"Testing {len(person_dirs)} people")
        print(f"{'=' * 60}\n")

        for person_idx, person_dir in enumerate(person_dirs, 1):
            person_name = person_dir.name
            images = list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png"))

            if len(images) < 2:
                continue  # Need at least 2 images for LOOCV

            print(f"Person {person_idx}/{len(person_dirs)}: {person_name} ({len(images)} images)")

            # LOOCV: For each image, train on N-1, test on 1
            for test_idx, test_img_path in enumerate(images):
                print(
                    f"  LOOCV {test_idx + 1}/{len(images)}: Testing {test_img_path.name}...",
                    end=" ",
                    flush=True,
                )
                # Build training set (all images EXCEPT test image)
                train_img_paths = [img for j, img in enumerate(images) if j != test_idx]

                # Use load_known_faces with LOOCV structure
                import shutil
                import tempfile

                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_path = Path(tmpdir)
                    tmp_person_dir = tmp_path / person_name
                    tmp_person_dir.mkdir()

                    # Copy training images to temp directory
                    for train_img in train_img_paths:
                        shutil.copy(train_img, tmp_person_dir / train_img.name)

                    # Load encodings from training images
                    # Both backends use min_face_size=80 at det_size=(640, 640)
                    min_face_size = 80
                    encodings, _ = factory.load_known_faces(
                        str(tmp_path), backend_name=backend_name, min_face_size=min_face_size
                    )

                    # Now test if held-out image matches
                    test_img = Image.open(test_img_path).convert("RGB")
                    test_img_np = np.array(test_img)

                    tolerance = 0.55 if backend_name == "face_recognition" else 0.42
                    matched, who = factory.best_match(
                        encodings,
                        test_img_np,
                        backend_name=backend_name,
                        tolerance=tolerance,
                        min_face_size=min_face_size,
                    )

                    results["total"] += 1

                    if matched and person_name in who:
                        results["correct"] += 1
                        print("✓ MATCH")
                    else:
                        results["incorrect"] += 1
                        print(f"✗ NO MATCH (got: {who if matched else 'no face'})")

        # Calculate metrics
        if results["total"] > 0:
            tpr = results["correct"] / results["total"]
            print(f"\n{backend_name} LOOCV Results:")
            print(f"  Total tests: {results['total']}")
            print(f"  Correct: {results['correct']}")
            print(f"  Incorrect: {results['incorrect']}")
            print(f"  TPR: {tpr:.1%}")

            # Should achieve >75% TPR with proper tolerance
            # Note: insightface has stricter face detection (more "no face" failures)
            # but is 12x faster than face_recognition
            assert tpr > 0.75, f"{backend_name} TPR {tpr:.1%} below 75% threshold"

    @pytest.mark.slow
    @pytest.mark.parametrize("backend_name", ["face_recognition", "insightface"])
    def test_cross_person_rejection(self, known_people_path: Path, backend_name: str):
        """
        Test that different people are correctly rejected (NOT matched).

        For each person P:
          For each image I of person P:
            For each OTHER person Q:
              Try to match I against Q's encodings
              Should NOT match (False Positive if it does)
        """
        results = {"true_negative": 0, "false_positive": 0, "total": 0}

        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]

        if len(person_dirs) < 2:
            pytest.skip("Need at least 2 people for cross-person testing")

        print(f"\n{'=' * 60}")
        print(f"Starting Cross-Person Rejection for {backend_name} backend")
        print(f"Testing {len(person_dirs)} people (3 images each)")
        print(f"{'=' * 60}\n")

        for test_person_idx, test_person_dir in enumerate(person_dirs, 1):
            test_person_name = test_person_dir.name
            test_images = list(test_person_dir.glob("*.jpg")) + list(test_person_dir.glob("*.png"))

            for img_idx, test_img_path in enumerate(
                test_images[:3], 1
            ):  # Limit to 3 images per person for speed
                person_idx = test_person_idx
                person_count = len(person_dirs)
                print(f"Person {person_idx}/{person_count}: {test_person_name} - Image {img_idx}/3")
                test_img = Image.open(test_img_path).convert("RGB")
                test_img_np = np.array(test_img)

                # Try matching against each OTHER person
                for other_person_dir in person_dirs:
                    if other_person_dir == test_person_dir:
                        continue  # Skip same person

                    other_person_name = other_person_dir.name
                    print(
                        f"  Testing {test_person_name} vs {other_person_name}...",
                        end=" ",
                        flush=True,
                    )

                    # Load encodings for the OTHER person
                    import shutil
                    import tempfile

                    with tempfile.TemporaryDirectory() as tmpdir:
                        tmp_path = Path(tmpdir)
                        tmp_other_dir = tmp_path / other_person_name
                        tmp_other_dir.mkdir()

                        # Copy other person's images
                        for img_path in other_person_dir.glob("*.jpg"):
                            shutil.copy(img_path, tmp_other_dir / img_path.name)

                        # Both backends use min_face_size=80
                        min_face_size = 80
                        encodings, _ = factory.load_known_faces(
                            str(tmp_path), backend_name=backend_name, min_face_size=min_face_size
                        )

                        # Try to match test image against wrong person
                        tolerance = 0.55 if backend_name == "face_recognition" else 0.42
                        matched, who = factory.best_match(
                            encodings,
                            test_img_np,
                            backend_name=backend_name,
                            tolerance=tolerance,
                            min_face_size=min_face_size,
                        )

                        results["total"] += 1

                        if matched:
                            results["false_positive"] += 1  # BAD: matched wrong person
                            print(f"✗ FALSE POSITIVE (matched: {who})")
                        else:
                            results["true_negative"] += 1  # GOOD: correctly rejected
                            print("✓ REJECTED")

        # Calculate metrics
        if results["total"] > 0:
            fpr = results["false_positive"] / results["total"]
            print(f"\n{backend_name} Cross-Person Results:")
            print(f"  Total tests: {results['total']}")
            print(f"  True Negatives: {results['true_negative']}")
            print(f"  False Positives: {results['false_positive']}")
            print(f"  FPR: {fpr:.1%}")

            # Should achieve <10% FPR
            assert fpr < 0.10, f"{backend_name} FPR {fpr:.1%} exceeds 10% threshold"

    @pytest.mark.slow
    @pytest.mark.parametrize("backend_name", ["face_recognition", "insightface"])
    def test_unknown_people_rejection(
        self, known_people_path: Path, unknown_people_path: Path, backend_name: str
    ):
        """
        Real-world FPR: Test 107 strangers against 4 known people.

        This is the CRITICAL production scenario: most images are unknown people.
        NONE of the 107 strangers should match any of the 4 known people.

        Expected: FPR < 5% (fewer than 5-6 false matches out of 107)
        """
        print(f"\n{'=' * 60}")
        print(f"Unknown People Rejection Test for {backend_name} backend")
        print("Testing 107 strangers vs 4 known people")
        print(f"{'=' * 60}\n")

        # Load ALL known people encodings
        min_face_size = 80
        known_encodings, _ = factory.load_known_faces(
            str(known_people_path), backend_name=backend_name, min_face_size=min_face_size
        )

        results = {"false_positives": 0, "true_negatives": 0, "no_face": 0, "total": 0}
        tolerance = 0.55 if backend_name == "face_recognition" else 0.42

        # Test each unknown person image
        unknown_images = list(unknown_people_path.glob("*.jpg")) + list(
            unknown_people_path.glob("*.png")
        )
        print(f"Testing {len(unknown_images)} unknown people images...")

        for i, unknown_img_path in enumerate(unknown_images, 1):
            if i % 10 == 0:
                print(f"  Progress: {i}/{len(unknown_images)}...")

            # Load and test unknown image
            unknown_img = Image.open(unknown_img_path).convert("RGB")
            unknown_img_np = np.array(unknown_img)

            matched, who = factory.best_match(
                known_encodings,
                unknown_img_np,
                backend_name=backend_name,
                tolerance=tolerance,
                min_face_size=min_face_size,
            )

            results["total"] += 1

            if not matched:
                results["true_negatives"] += 1  # GOOD: correctly rejected
            elif who == []:  # No face detected
                results["no_face"] += 1
                results["true_negatives"] += 1  # Count as correct rejection
            else:
                results["false_positives"] += 1  # BAD: matched a known person!
                print(f"  ✗ FALSE POSITIVE: {unknown_img_path.name} matched {who}")

        # Calculate metrics
        if results["total"] > 0:
            fpr = results["false_positives"] / results["total"]
            print(f"\n{backend_name} Unknown People Results:")
            print(f"  Total tests: {results['total']}")
            print(f"  True Negatives: {results['true_negatives']} ({results['no_face']} no-face)")
            print(f"  False Positives: {results['false_positives']}")
            print(f"  FPR: {fpr:.1%}")

            # InsightFace achieves 0% FPR (perfect)
            # face_recognition has ~11% FPR (privacy concern in production)
            # Fail if FPR exceeds 15% (unusable for production)
            assert fpr < 0.15, f"{backend_name} FPR {fpr:.1%} exceeds 15% threshold"

            # Warn if FPR > 5% (acceptable but not ideal)
            if fpr > 0.05:
                print(
                    f"\n⚠️  WARNING: {backend_name} FPR {fpr:.1%} exceeds 5% - "
                    f"consider insightface for better precision"
                )


class TestBackendPerformance:
    """Compare performance metrics between backends."""

    @pytest.mark.slow
    @pytest.mark.parametrize("backend_name", ["face_recognition", "insightface"])
    def test_model_load_time(self, backend_name: str):
        """Measure time to load/initialize each backend model."""
        # Reset singleton for insightface
        if backend_name == "insightface":
            import dmaf.face_recognition.insightface_backend as ib

            ib._app_instance = None

        start = time.time()

        # Trigger model loading
        if backend_name == "face_recognition":
            import face_recognition

            # dlib model loads on first use
            dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
            face_recognition.face_locations(dummy_img)
        else:
            import dmaf.face_recognition.insightface_backend as ib

            _ = ib._get_app()

        load_time_ms = (time.time() - start) * 1000

        print(f"\n{backend_name} model load time: {load_time_ms:.0f}ms")

        # Reasonable thresholds
        if backend_name == "face_recognition":
            assert load_time_ms < 5000, "dlib should load in <5s"
        else:
            assert load_time_ms < 10000, "insightface should load in <10s"

    @pytest.mark.slow
    @pytest.mark.parametrize("backend_name", ["face_recognition", "insightface"])
    def test_encoding_speed(self, known_people_path: Path, backend_name: str):
        """Measure per-image encoding time."""
        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]
        if not person_dirs:
            pytest.skip("No person directories found")

        # Get first image
        test_img_path = None
        for person_dir in person_dirs:
            images = list(person_dir.glob("*.jpg"))
            if images:
                test_img_path = images[0]
                break

        if not test_img_path:
            pytest.skip("No test images found")

        img = Image.open(test_img_path).convert("RGB")
        img_np = np.array(img)

        # Warm up (first call may load model)
        factory.best_match({}, img_np, backend_name=backend_name)

        # Measure encoding time
        start = time.time()
        factory.best_match({}, img_np, backend_name=backend_name)
        encoding_time_ms = (time.time() - start) * 1000

        print(f"\n{backend_name} encoding time: {encoding_time_ms:.1f}ms")

        # Reasonable thresholds
        assert encoding_time_ms < 1000, f"{backend_name} encoding should be <1s per image"


# Note: Memory usage testing requires psutil and is optional
# Tolerance sweep is done separately as it's more of a calibration tool
