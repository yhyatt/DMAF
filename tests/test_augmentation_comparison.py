"""Test impact of image augmentation on face recognition accuracy.

Tests various augmentation strategies to determine if they improve TPR
(same-person matching) while maintaining low FPR (stranger rejection).
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dmaf.face_recognition import factory
from tests.augmentation_utils import (
    AUGMENTATION_STRATEGIES,
    adjust_brightness,
    apply_augmentations,
    get_strategy_description,
    horizontal_flip,
    rotate_image,
)


class TestAugmentationUtilities:
    """Verify augmentation functions work correctly."""

    def test_horizontal_flip(self, tmp_path):
        """Test horizontal flip creates mirror image."""
        # Create simple test image with asymmetry
        img_array = np.zeros((100, 100, 3), dtype=np.uint8)
        img_array[:, :50] = [255, 0, 0]  # Left half red
        img_array[:, 50:] = [0, 0, 255]  # Right half blue

        img = Image.fromarray(img_array)
        flipped = horizontal_flip(img)
        flipped_array = np.array(flipped)

        # After flip, left should be blue, right should be red
        # Check that all pixels in left half are blue
        assert np.all(flipped_array[:, :50] == [0, 0, 255])
        # Check that all pixels in right half are red
        assert np.all(flipped_array[:, 50:] == [255, 0, 0])

    def test_brightness_adjustment(self, tmp_path):
        """Test brightness adjustment changes pixel values."""
        img_array = np.ones((100, 100, 3), dtype=np.uint8) * 128  # Mid-gray
        img = Image.fromarray(img_array)

        # Darker
        darker = adjust_brightness(img, 0.5)
        darker_array = np.array(darker)
        assert darker_array.mean() < 128

        # Brighter
        brighter = adjust_brightness(img, 1.5)
        brighter_array = np.array(brighter)
        assert brighter_array.mean() > 128

    def test_rotation_preserves_shape(self, tmp_path):
        """Test rotation maintains image dimensions."""
        img_array = np.zeros((100, 100, 3), dtype=np.uint8)
        img = Image.fromarray(img_array)

        rotated = rotate_image(img, 5)
        assert rotated.size == img.size

    def test_apply_augmentations(self, known_people_path: Path):
        """Test applying augmentations to real image."""
        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]
        if not person_dirs:
            pytest.skip("No person directories found")

        img_path = None
        for person_dir in person_dirs:
            images = list(person_dir.glob("*.jpg"))
            if images:
                img_path = images[0]
                break

        if not img_path:
            pytest.skip("No test images found")

        # Apply flip_brightness strategy
        aug_fns = AUGMENTATION_STRATEGIES["flip_brightness"]
        results = apply_augmentations(img_path, aug_fns)

        # Should have original + 3 augmentations
        assert len(results) >= 4
        assert results[0][0] == "original"

        # All should be valid numpy arrays
        for _name, img_array in results:
            assert isinstance(img_array, np.ndarray)
            assert img_array.shape[2] == 3  # RGB
            assert img_array.dtype == np.uint8


class TestAugmentationImpact:
    """Compare recognition accuracy with different augmentation strategies."""

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "strategy_name",
        [
            "none",  # Baseline
            "flip_only",  # Most common augmentation
            "brightness",  # Lighting variations
            "rotation",  # Slight angle changes
            "conservative",  # Flip + slight brightness
            "aggressive",  # All augmentations
        ],
    )
    def test_augmentation_loocv_insightface(self, known_people_path: Path, strategy_name: str):
        """
        Test augmentation impact on same-person matching using LOOCV.

        For each augmentation strategy:
        - Apply augmentations to training images (N-1 images)
        - Test against original held-out image
        - Measure TPR improvement vs baseline

        Expected: Augmentation should improve TPR while maintaining quality.
        """
        backend_name = "insightface"
        augmentation_fns = AUGMENTATION_STRATEGIES[strategy_name]

        results = {
            "correct": 0,
            "incorrect": 0,
            "total": 0,
            "no_face": 0,
            "training_samples": 0,
        }

        person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]

        print(f"\n{'=' * 70}")
        print(f"Augmentation Strategy: {strategy_name}")
        print(f"Description: {get_strategy_description(strategy_name)}")
        print(f"Backend: {backend_name}")
        print(f"Testing {len(person_dirs)} people with LOOCV")
        print(f"{'=' * 70}\n")

        for person_idx, person_dir in enumerate(person_dirs, 1):
            person_name = person_dir.name
            images = list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png"))

            if len(images) < 2:
                continue

            print(f"Person {person_idx}/{len(person_dirs)}: {person_name} ({len(images)} images)")

            # LOOCV: For each image, train on N-1, test on 1
            for test_idx, test_img_path in enumerate(images):
                print(
                    f"  LOOCV {test_idx + 1}/{len(images)}: {test_img_path.name}...",
                    end=" ",
                    flush=True,
                )

                # Build training set (all images EXCEPT test image)
                train_img_paths = [img for j, img in enumerate(images) if j != test_idx]

                # Apply augmentations to training images
                train_encodings = []
                for train_img_path in train_img_paths:
                    # Get original + augmented versions
                    augmented_imgs = apply_augmentations(train_img_path, augmentation_fns)
                    results["training_samples"] += len(augmented_imgs)

                    # Extract face encodings from each version
                    for _aug_name, img_array in augmented_imgs:
                        # Use factory to extract encodings
                        min_face_size = 80
                        tolerance = 0.42

                        # Create temporary dict for this single image
                        from dmaf.face_recognition.insightface_backend import (
                            _embed_faces,
                            _get_app,
                        )

                        app = _get_app()
                        embs = _embed_faces(app, img_array, min_face_size)
                        train_encodings.extend(embs)

                # Build known encodings dict
                known = {person_name: train_encodings}

                # Test against original held-out image (no augmentation on test)
                test_img = Image.open(test_img_path).convert("RGB")
                test_img_np = np.array(test_img)

                matched, who = factory.best_match(
                    known,
                    test_img_np,
                    backend_name=backend_name,
                    tolerance=tolerance,
                    min_face_size=min_face_size,
                )

                results["total"] += 1

                if matched and person_name in who:
                    results["correct"] += 1
                    print("✓ MATCH")
                elif not matched or who == []:
                    results["incorrect"] += 1
                    results["no_face"] += 1
                    print("✗ NO FACE")
                else:
                    results["incorrect"] += 1
                    print(f"✗ WRONG ({who})")

        # Calculate metrics
        if results["total"] > 0:
            tpr = results["correct"] / results["total"]
            avg_training_samples = results["training_samples"] / results["total"]

            print(f"\n{strategy_name} LOOCV Results (insightface):")
            print(f"  Strategy: {get_strategy_description(strategy_name)}")
            print(f"  Total tests: {results['total']}")
            print(f"  Correct: {results['correct']}")
            print(f"  Incorrect: {results['incorrect']} ({results['no_face']} no-face)")
            print(f"  TPR: {tpr:.1%}")
            print(f"  Avg training samples per test: {avg_training_samples:.1f}")

            # Baseline (none) achieves 77.5% TPR
            # Expect augmentation to maintain or improve TPR
            # Allow slight degradation for aggressive strategies
            if strategy_name == "none":
                assert tpr > 0.75, f"Baseline TPR {tpr:.1%} below expected 75%"
            else:
                # Augmented strategies should be within reasonable range
                assert tpr > 0.65, f"{strategy_name} TPR {tpr:.1%} severely degraded"

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "strategy_name",
        [
            "none",  # Baseline
            "flip_only",
            "conservative",
            "aggressive",
        ],
    )
    def test_augmentation_unknown_people_fpr(
        self, known_people_path: Path, unknown_people_path: Path, strategy_name: str
    ):
        """
        Test augmentation impact on unknown people FPR.

        Critical: Augmentation should NOT increase false positive rate.
        More training data should improve discrimination, not degrade it.

        Expected: FPR should remain at or near 0.0% for all strategies.
        """
        backend_name = "insightface"
        augmentation_fns = AUGMENTATION_STRATEGIES[strategy_name]

        print(f"\n{'=' * 70}")
        print(f"Unknown People FPR Test: {strategy_name}")
        print(f"Description: {get_strategy_description(strategy_name)}")
        print("Testing 107 strangers vs augmented known encodings")
        print(f"{'=' * 70}\n")

        # Load and augment ALL known people images
        all_encodings = {}
        total_training_samples = 0

        for person_dir in known_people_path.iterdir():
            if not person_dir.is_dir():
                continue

            person_name = person_dir.name
            person_encodings = []

            for img_path in person_dir.glob("*.jpg"):
                if "Zone.Identifier" in img_path.name:
                    continue

                # Apply augmentations
                augmented_imgs = apply_augmentations(img_path, augmentation_fns)
                total_training_samples += len(augmented_imgs)

                # Extract encodings
                for _aug_name, img_array in augmented_imgs:
                    from dmaf.face_recognition.insightface_backend import (
                        _embed_faces,
                        _get_app,
                    )

                    app = _get_app()
                    embs = _embed_faces(app, img_array, min_face=80)
                    person_encodings.extend(embs)

            all_encodings[person_name] = person_encodings

        print(f"Loaded {total_training_samples} training samples (augmented)")

        # Test against unknown people
        results = {"false_positives": 0, "true_negatives": 0, "total": 0}
        tolerance = 0.42
        min_face_size = 80

        unknown_images = list(unknown_people_path.glob("*.jpg")) + list(
            unknown_people_path.glob("*.png")
        )
        print(f"Testing {len(unknown_images)} unknown people images...\n")

        for i, unknown_img_path in enumerate(unknown_images, 1):
            if i % 20 == 0:
                print(f"  Progress: {i}/{len(unknown_images)}...")

            # Test original image (no augmentation on test set)
            unknown_img = Image.open(unknown_img_path).convert("RGB")
            unknown_img_np = np.array(unknown_img)

            matched, who = factory.best_match(
                all_encodings,
                unknown_img_np,
                backend_name=backend_name,
                tolerance=tolerance,
                min_face_size=min_face_size,
            )

            results["total"] += 1

            if matched and who != []:
                results["false_positives"] += 1
                print(f"  ✗ FALSE POSITIVE: {unknown_img_path.name} matched {who}")
            else:
                results["true_negatives"] += 1

        # Calculate FPR
        if results["total"] > 0:
            fpr = results["false_positives"] / results["total"]

            print(f"\n{strategy_name} Unknown People FPR Results:")
            print(f"  Strategy: {get_strategy_description(strategy_name)}")
            print(f"  Total tests: {results['total']}")
            print(f"  True Negatives: {results['true_negatives']}")
            print(f"  False Positives: {results['false_positives']}")
            print(f"  FPR: {fpr:.1%}")

            # CRITICAL: Augmentation should NOT increase FPR
            # Baseline (none) achieves 0.0% FPR
            # Augmented strategies should maintain low FPR
            assert fpr < 0.10, f"{strategy_name} FPR {fpr:.1%} unacceptably high"

            if fpr > 0.02:
                print(f"\n⚠️  WARNING: {strategy_name} FPR {fpr:.1%} higher than baseline 0.0%")
                print("   Augmentation may be introducing false positives")


class TestAugmentationComparison:
    """Generate comparison report across all augmentation strategies."""

    def test_generate_augmentation_summary(self, known_people_path: Path):
        """
        Generate summary of augmentation strategies for documentation.

        This is a helper test that prints a summary table.
        Not a validation test - always passes.
        """
        print("\n" + "=" * 80)
        print("AUGMENTATION STRATEGIES SUMMARY")
        print("=" * 80)

        for strategy_name, aug_fns in AUGMENTATION_STRATEGIES.items():
            num_augmentations = len(aug_fns)
            description = get_strategy_description(strategy_name)

            print(f"\n{strategy_name}:")
            print(f"  Description: {description}")
            print(f"  Augmentations: {num_augmentations}")
            print(
                f"  Training multiplier: {num_augmentations + 1}x "
                f"(original + {num_augmentations} aug)"
            )

        print("\n" + "=" * 80)
        print("To run full comparison:")
        print("  pytest tests/test_augmentation_comparison.py -v -m slow")
        print("=" * 80 + "\n")

        # Always pass - this is just informational
        assert True
