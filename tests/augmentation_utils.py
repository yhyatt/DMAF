"""Image augmentation utilities for face recognition testing.

Provides various augmentation strategies to test impact on recognition accuracy.
"""

from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def horizontal_flip(img: Image.Image) -> Image.Image:
    """Flip image horizontally (mirror)."""
    return img.transpose(Image.FLIP_LEFT_RIGHT)


def adjust_brightness(img: Image.Image, factor: float) -> Image.Image:
    """
    Adjust image brightness.

    Args:
        factor: Brightness multiplier (0.5 = darker, 1.5 = brighter)
    """
    enhancer = ImageEnhance.Brightness(img)
    return enhancer.enhance(factor)


def adjust_contrast(img: Image.Image, factor: float) -> Image.Image:
    """
    Adjust image contrast.

    Args:
        factor: Contrast multiplier (0.5 = less contrast, 1.5 = more contrast)
    """
    enhancer = ImageEnhance.Contrast(img)
    return enhancer.enhance(factor)


def rotate_image(img: Image.Image, degrees: float) -> Image.Image:
    """
    Rotate image by given degrees.

    Args:
        degrees: Rotation angle (positive = counterclockwise)
    """
    return img.rotate(degrees, resample=Image.BICUBIC, expand=False, fillcolor=(128, 128, 128))


def gaussian_blur(img: Image.Image, radius: float = 1.0) -> Image.Image:
    """
    Apply Gaussian blur filter.

    Args:
        radius: Blur radius (higher = more blur)
    """
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def color_jitter(img: Image.Image, saturation_factor: float) -> Image.Image:
    """
    Adjust color saturation.

    Args:
        saturation_factor: Saturation multiplier (0 = grayscale, 2 = very saturated)
    """
    enhancer = ImageEnhance.Color(img)
    return enhancer.enhance(saturation_factor)


# Augmentation strategies: (name, list of augmentation functions)
AUGMENTATION_STRATEGIES = {
    "none": [],
    "flip_only": [
        horizontal_flip,
    ],
    "brightness": [
        lambda img: adjust_brightness(img, 0.7),  # Darker
        lambda img: adjust_brightness(img, 1.3),  # Brighter
    ],
    "rotation": [
        lambda img: rotate_image(img, -5),  # Slight left rotation
        lambda img: rotate_image(img, 5),  # Slight right rotation
    ],
    "contrast": [
        lambda img: adjust_contrast(img, 0.8),  # Less contrast
        lambda img: adjust_contrast(img, 1.2),  # More contrast
    ],
    "blur": [
        lambda img: gaussian_blur(img, radius=1.0),
    ],
    "color": [
        lambda img: color_jitter(img, 0.7),  # Desaturated
        lambda img: color_jitter(img, 1.3),  # More saturated
    ],
    # Combined strategies
    "flip_brightness": [
        horizontal_flip,
        lambda img: adjust_brightness(img, 0.7),
        lambda img: adjust_brightness(img, 1.3),
    ],
    "flip_rotation": [
        horizontal_flip,
        lambda img: rotate_image(img, -5),
        lambda img: rotate_image(img, 5),
    ],
    "conservative": [
        # Conservative augmentations: flip + slight brightness
        horizontal_flip,
        lambda img: adjust_brightness(img, 0.8),
        lambda img: adjust_brightness(img, 1.2),
    ],
    "aggressive": [
        # All augmentations combined
        horizontal_flip,
        lambda img: adjust_brightness(img, 0.7),
        lambda img: adjust_brightness(img, 1.3),
        lambda img: rotate_image(img, -5),
        lambda img: rotate_image(img, 5),
        lambda img: adjust_contrast(img, 0.8),
        lambda img: adjust_contrast(img, 1.2),
        lambda img: gaussian_blur(img, radius=1.0),
    ],
}


def apply_augmentations(
    img_path: Path, augmentation_fns: list[Callable[[Image.Image], Image.Image]]
) -> list[tuple[str, np.ndarray]]:
    """
    Apply augmentation functions to an image.

    Args:
        img_path: Path to original image
        augmentation_fns: List of augmentation functions to apply

    Returns:
        List of (name, augmented_image_array) tuples.
        Always includes original image first.
    """
    img = Image.open(img_path).convert("RGB")
    results = [("original", np.array(img))]

    for i, aug_fn in enumerate(augmentation_fns):
        try:
            augmented_img = aug_fn(img)
            results.append((f"aug_{i}", np.array(augmented_img)))
        except Exception as e:
            # Skip failed augmentations
            print(f"Warning: Augmentation {i} failed for {img_path.name}: {e}")
            continue

    return results


def get_strategy_description(strategy_name: str) -> str:
    """Get human-readable description of augmentation strategy."""
    descriptions = {
        "none": "No augmentation (baseline)",
        "flip_only": "Horizontal flip only",
        "brightness": "Brightness variations (±30%)",
        "rotation": "Small rotations (±5°)",
        "contrast": "Contrast adjustment (±20%)",
        "blur": "Slight Gaussian blur",
        "color": "Saturation variations (±30%)",
        "flip_brightness": "Flip + brightness variations",
        "flip_rotation": "Flip + small rotations",
        "conservative": "Flip + slight brightness (±20%)",
        "aggressive": "All augmentations combined (8 variations)",
    }
    return descriptions.get(strategy_name, f"Custom strategy: {strategy_name}")
