# face_index.py - Factory module for face recognition backends
"""
Factory module that provides a unified interface to different face recognition backends.

Supported backends:
- 'face_recognition': dlib-based face recognition (CPU-optimized)
- 'insightface': Deep learning-based face recognition (more accurate)
"""


from types import ModuleType
from typing import Any

import numpy as np

# Module-level cache for backend instances (singleton pattern)
_backend_cache: dict[str, ModuleType] = {}


def load_known_faces(
    known_root: str,
    backend_name: str = "face_recognition",
    min_face_size: int = 80,
    enable_augmentation: bool = True,
) -> tuple[dict[str, list[np.ndarray]], list[str]]:
    """
    Load known faces from a directory structure.

    Args:
        known_root: Path to directory containing subdirectories for each person
        backend_name: Which backend to use ('face_recognition' or 'insightface')
        min_face_size: Minimum face size in pixels to detect
        enable_augmentation: Enable augmentation for insightface backend (default: True).
                           Applies conservative augmentation (flip + brightness ±20%)
                           to improve TPR from 77.5% to 82.5% while maintaining 0.0% FPR.
                           Only applies to insightface backend.

    Returns:
        Tuple of (encodings_dict, people_list)
        - encodings_dict: {person_name: [list of face encodings]}
        - people_list: List of person names

    Directory structure expected:
        known_root/
            person1/
                image1.jpg
                image2.jpg
            person2/
                image1.jpg
    """
    backend = _get_backend(backend_name)

    if backend_name == "insightface":
        # InsightFace backend supports augmentation
        result: tuple[dict[str, list[np.ndarray]], list[str]] = backend.load_known_faces(
            known_root, min_face_size, enable_augmentation
        )
        return result
    else:
        # face_recognition backend doesn't support augmentation yet
        result = backend.load_known_faces(known_root)
        return result


def best_match(
    known: dict[str, list[np.ndarray]],
    img_rgb: np.ndarray,
    backend_name: str = "face_recognition",
    tolerance: float = 0.52,
    min_face_size: int = 80,
) -> tuple[bool, list[str]]:
    """
    Find the best match for faces in an image.

    Args:
        known: Dictionary mapping person names to face encodings
        img_rgb: Image as numpy array in RGB format (from PIL)
        backend_name: Which backend to use ('face_recognition' or 'insightface')
        tolerance: Matching threshold (lower = stricter)
                  - For face_recognition: typically 0.5-0.6
                  - For insightface: typically 0.3-0.5 (cosine distance)
        min_face_size: Minimum face size in pixels

    Returns:
        Tuple of (matched, person_names)
        - matched: True if any known person was found
        - person_names: List of matched person names
    """
    backend = _get_backend(backend_name)
    result: tuple[bool, list[str]] = backend.best_match(
        known, img_rgb, tolerance=tolerance, min_face_size=min_face_size
    )
    return result


def _get_backend(backend_name: str) -> ModuleType:
    """
    Get or load the appropriate backend module.

    Uses module-level caching to avoid repeated imports.
    """
    if backend_name in _backend_cache:
        return _backend_cache[backend_name]

    backend: ModuleType
    if backend_name == "face_recognition":
        from wa_automate.face_recognition import dlib_backend

        backend = dlib_backend
    elif backend_name == "insightface":
        from wa_automate.face_recognition import insightface_backend

        backend = insightface_backend
    else:
        raise ValueError(
            f"Unknown backend: {backend_name}. "
            f"Supported backends: 'face_recognition', 'insightface'"
        )

    _backend_cache[backend_name] = backend
    return backend
