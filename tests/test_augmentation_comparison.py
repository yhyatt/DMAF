"""Test impact of image augmentation on face recognition accuracy.

Tests various augmentation strategies to determine if they improve TPR
(same-person matching) while maintaining low FPR (stranger rejection).
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

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


class TestAugmentationIntegration:
    """
    Integration test placeholders for augmentation functionality.

    All comprehensive LOOCV tests have been moved to scripts/benchmark_augmentation.py
    to keep the unit test suite fast (<10 seconds).

    The utility tests in TestAugmentationUtilities verify that augmentation
    functions work correctly, which is sufficient for CI/CD.
    """

    def test_augmentation_strategies_defined(self):
        """
        Fast smoke test: verify all augmentation strategies are defined and importable.

        For comprehensive LOOCV benchmarking of augmentation impact, run:
            python scripts/benchmark_augmentation.py
        """
        # Verify all expected strategies exist
        expected_strategies = [
            "none",
            "flip_only",
            "brightness",
            "rotation",
            "conservative",
            "aggressive",
        ]

        for strategy_name in expected_strategies:
            assert (
                strategy_name in AUGMENTATION_STRATEGIES
            ), f"Strategy '{strategy_name}' not found in AUGMENTATION_STRATEGIES"

            # Verify strategy has augmentation functions (or empty list for 'none')
            aug_fns = AUGMENTATION_STRATEGIES[strategy_name]
            assert isinstance(
                aug_fns, list
            ), f"Strategy '{strategy_name}' should return a list of functions"

            # Verify description is available
            description = get_strategy_description(strategy_name)
            assert (
                isinstance(description, str) and len(description) > 0
            ), f"Strategy '{strategy_name}' should have a non-empty description"

        # Verify baseline has no augmentations
        assert (
            len(AUGMENTATION_STRATEGIES["none"]) == 0
        ), "Baseline strategy should have no augmentations"

        # Verify other strategies have augmentations
        assert (
            len(AUGMENTATION_STRATEGIES["flip_only"]) > 0
        ), "flip_only strategy should have at least one augmentation"

        print("\n✅ All augmentation strategies are properly defined")
        print(f"   Strategies available: {', '.join(expected_strategies)}")
        print("\nFor comprehensive benchmarking, run:")
        print("    python scripts/benchmark_augmentation.py")


class TestAugmentationComparison:
    """Generate comparison report across all augmentation strategies."""

    def test_generate_augmentation_summary(self):
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
        print("To run full augmentation benchmark:")
        print("  python scripts/benchmark_augmentation.py")
        print("=" * 80 + "\n")

        # Always pass - this is just informational
        assert True
