# face_index.py - Factory module for face recognition backends
"""
Factory module that provides a unified interface to different face recognition backends.

Supported backends:
- 'face_recognition': dlib-based face recognition (CPU-optimized)
- 'insightface': Deep learning-based face recognition (more accurate)
- 'auraface': Apache 2.0 licensed face recognition (fully commercial use)
"""

import hashlib
import logging
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import numpy as np

logger = logging.getLogger(__name__)

# Module-level cache for backend instances (singleton pattern)
_backend_cache: dict[str, ModuleType] = {}


def _compute_files_hash(known_root: str) -> str:
    """
    Compute hash of known_people directory state.

    Includes file paths and modification times to detect any changes.
    If any file is added/removed/modified, hash will change.

    Args:
        known_root: Path to known_people directory

    Returns:
        SHA256 hash of directory state
    """
    root_path = Path(known_root)
    valid_extensions = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

    # Collect all image files with their modification times
    files_info = []
    for person_dir in sorted(root_path.iterdir()):
        if not person_dir.is_dir():
            continue

        for img_path in sorted(person_dir.glob("*.*")):
            if (
                "Zone.Identifier" in img_path.name
                or img_path.suffix.lower() not in valid_extensions
            ):
                continue

            try:
                mtime = img_path.stat().st_mtime
                # Include relative path and mtime
                files_info.append(f"{img_path.relative_to(root_path)}:{mtime:.6f}")
            except (OSError, ValueError):
                continue

    # Hash the sorted list
    content = "\n".join(files_info)
    return hashlib.sha256(content.encode()).hexdigest()


def _make_cache_key(
    backend_name: str,
    min_face_size: int,
    enable_augmentation: bool,
    det_thresh_known: float,
    return_best_only: bool,
    return_per_file: bool,
) -> str:
    """
    Create cache key from parameters.

    Args:
        backend_name: Face recognition backend
        min_face_size: Minimum face size in pixels
        enable_augmentation: Whether augmentation is enabled
        det_thresh_known: Detection threshold for known faces
        return_best_only: Whether to return only best face per image
        return_per_file: Whether to return per-file metadata

    Returns:
        Cache key string
    """
    return (
        f"{backend_name}_mfs{min_face_size}_aug{int(enable_augmentation)}"
        f"_detknown{det_thresh_known:.2f}_best{int(return_best_only)}"
        f"_perfile{int(return_per_file)}"
    )


def load_known_faces(
    known_root: str,
    backend_name: str = "face_recognition",
    min_face_size: int = 80,
    enable_augmentation: bool = True,
    det_thresh_known: float = 0.3,
    return_best_only: bool = False,
    return_per_file: bool = False,
    db: Any = None,
) -> tuple[dict[str, list[np.ndarray]] | dict[str, list[tuple[str, list[np.ndarray]]]], list[str]]:
    """
    Load known faces from a directory structure with optional caching.

    Args:
        known_root: Path to directory containing subdirectories for each person
        backend_name: Which backend to use ('face_recognition', 'insightface', or 'auraface')
        min_face_size: Minimum face size in pixels to detect
        enable_augmentation: Enable augmentation for insightface/auraface backends (default: True).
                           Applies conservative augmentation (flip + brightness ±20%)
                           to improve TPR from 77.5% to 82.5% while maintaining 0.0% FPR.
                           Only applies to insightface and auraface backends.
        det_thresh_known: Detection confidence threshold for known_people images
                         (0.0-1.0). Lower than det_thresh for test images because
                         we assume faces exist in training data.
                         Only applies to insightface backend.
        return_best_only: Use only highest confidence face per image
                         (handles multi-person photos)
        return_per_file: Return per-file metadata for LOOCV filtering (default: False).
                        When True, returns {person: [(filename, [embeddings])]}
                        instead of {person: [embeddings]}.
                        Useful for LOOCV where you need to exclude specific files
                        from training set.
        db: Optional Database instance for caching embeddings (speeds up startup 100x)

    Returns:
        Tuple of (encodings_dict, people_list) where:
        - If return_per_file=False: encodings_dict = {person_name: [list of face encodings]}
        - If return_per_file=True: encodings_dict = {person_name: [(filename, [embeddings])]}
        - people_list: List of person names

    Directory structure expected:
        known_root/
            person1/
                image1.jpg
                image2.jpg
            person2/
                image1.jpg
    """
    # Try cache if database provided (cache only supports flat format)
    if db is not None and hasattr(db, "get_cached_embeddings") and not return_per_file:
        cache_key = _make_cache_key(
            backend_name,
            min_face_size,
            enable_augmentation,
            det_thresh_known,
            return_best_only,
            return_per_file,
        )
        files_hash = _compute_files_hash(known_root)

        cached = db.get_cached_embeddings(cache_key, files_hash)
        if cached is not None:
            logger.info("Loaded face embeddings from cache (instant)")
            # Cast to the return type since we know cache only stores flat format
            return cast(
                tuple[
                    dict[str, list[np.ndarray]] | dict[str, list[tuple[str, list[np.ndarray]]]],
                    list[str],
                ],
                cached,
            )

        logger.info("Cache miss - computing embeddings...")

    backend = _get_backend(backend_name)

    # Compute embeddings (slow)
    if backend_name in ("insightface", "auraface"):
        # InsightFace and AuraFace backends support augmentation, det_thresh_known,
        # return_best_only, and return_per_file
        result: tuple[
            dict[str, list[np.ndarray]] | dict[str, list[tuple[str, list[np.ndarray]]]], list[str]
        ] = backend.load_known_faces(
            known_root,
            min_face_size,
            enable_augmentation,
            det_thresh_known,
            return_best_only,
            return_per_file,
        )
    else:
        # face_recognition backend doesn't support these features
        result = backend.load_known_faces(known_root)
        # If per-file requested but backend doesn't support it, we can't provide it
        if return_per_file:
            raise ValueError(f"{backend_name} backend does not support return_per_file mode")

    # Save to cache if database provided (cache only supports flat format)
    if db is not None and hasattr(db, "save_cached_embeddings") and not return_per_file:
        cache_key = _make_cache_key(
            backend_name,
            min_face_size,
            enable_augmentation,
            det_thresh_known,
            return_best_only,
            return_per_file,
        )
        files_hash = _compute_files_hash(known_root)
        db.save_cached_embeddings(cache_key, files_hash, result[0], result[1])
        logger.info("Saved embeddings to cache")

    return result


def best_match(
    known: dict[str, list[np.ndarray]],
    img_rgb: np.ndarray,
    backend_name: str = "face_recognition",
    tolerance: float = 0.52,
    min_face_size: int = 80,
    det_thresh: float = 0.4,
    return_best_only: bool = False,
    return_scores: bool = False,
) -> tuple[bool, list[str]] | tuple[bool, list[str], dict[str, float]]:
    """
    Find the best match for faces in an image.

    Args:
        known: Dictionary mapping person names to face encodings
        img_rgb: Image as numpy array in RGB format (from PIL)
        backend_name: Which backend to use ('face_recognition', 'insightface', or 'auraface')
        tolerance: Matching threshold (lower = stricter)
                  - For face_recognition: typically 0.5-0.6
                  - For insightface/auraface: typically 0.3-0.5 (cosine distance)
        min_face_size: Minimum face size in pixels
        det_thresh: Detection confidence threshold (0.0-1.0). Only applies to insightface/auraface.
        return_best_only: If True, use only highest confidence face (insightface/auraface only)
        return_scores: If True, return similarity scores for all known people

    Returns:
        If return_scores=False:
            Tuple of (matched, person_names)
            - matched: True if any known person was found
            - person_names: List of matched person names
        If return_scores=True:
            Tuple of (matched, person_names, scores)
            - matched: True if any known person was found
            - person_names: List of matched person names
            - scores: Dict mapping person names to best similarity scores (0.0-1.0)
    """
    backend = _get_backend(backend_name)

    if backend_name in ("insightface", "auraface"):
        result: tuple[bool, list[str]] | tuple[bool, list[str], dict[str, float]] = (
            backend.best_match(
                known,
                img_rgb,
                tolerance=tolerance,
                min_face_size=min_face_size,
                det_thresh=det_thresh,
                return_best_only=return_best_only,
                return_scores=return_scores,
            )
        )
    else:
        result = backend.best_match(
            known,
            img_rgb,
            tolerance=tolerance,
            min_face_size=min_face_size,
            return_scores=return_scores,
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
        from dmaf.face_recognition import dlib_backend

        backend = dlib_backend
    elif backend_name == "insightface":
        from dmaf.face_recognition import insightface_backend

        backend = insightface_backend
    elif backend_name == "auraface":
        from dmaf.face_recognition import auraface_backend

        backend = auraface_backend
    else:
        raise ValueError(
            f"Unknown backend: {backend_name}. "
            f"Supported backends: 'face_recognition', 'insightface', 'auraface'"
        )

    _backend_cache[backend_name] = backend
    return backend
