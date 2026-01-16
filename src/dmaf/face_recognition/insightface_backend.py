# face_index.py (InsightFace backend)
import threading
from pathlib import Path

import numpy as np
from insightface.app import FaceAnalysis
from PIL import Image

# Thread-safe cache for FaceAnalysis models (cached by det_thresh)
_app_lock = threading.Lock()
_app_cache: dict[float, FaceAnalysis] = {}


def _get_app(det_thresh: float = 0.4) -> FaceAnalysis:
    """
    Get or initialize the FaceAnalysis model instance for given det_thresh.

    Uses thread-safe caching pattern to avoid reloading the model.
    The model is ~600MB and takes several seconds to load, so caching is critical.
    Multiple instances can be cached with different det_thresh values.

    Args:
        det_thresh: Detection confidence threshold (0.0-1.0). Lower = more faces detected.
                   0.4 = balanced, 0.5 = strict, 0.35 = permissive
    """
    global _app_cache

    if det_thresh not in _app_cache:
        with _app_lock:
            # Double-check locking pattern
            if det_thresh not in _app_cache:
                app = FaceAnalysis(
                    name="buffalo_l"
                )  # balanced accuracy/speed (ResNet-50, 99.7% LFW)
                # ctx_id=-1 = CPU; set 0 if you configured CUDA in WSL
                # Keep det_size=(640, 640) - larger sizes need proportionally larger min_face_size
                app.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=det_thresh)
                _app_cache[det_thresh] = app

    return _app_cache[det_thresh]


def _img_to_np(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


def _embed_faces(
    app: FaceAnalysis, img_np: np.ndarray, min_face: int, return_best_only: bool = False
) -> list[np.ndarray]:
    """
    Extract face embeddings from an image.

    Args:
        app: FaceAnalysis instance
        img_np: Image as numpy array
        min_face: Minimum face size in pixels
        return_best_only: If True and multiple faces detected, return only highest confidence face

    Returns:
        List of face embeddings (or single-element list if return_best_only=True)
    """
    faces = app.get(img_np)

    # Filter tiny detections and collect with confidence scores
    valid_faces = []
    for f in faces:
        x1, y1, x2, y2 = map(int, f.bbox)
        if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
            # Store (confidence, embedding) tuple
            valid_faces.append((f.det_score, f.normed_embedding.astype(np.float32)))

    if not valid_faces:
        return []

    # If return_best_only and multiple faces, select highest confidence
    if return_best_only and len(valid_faces) > 1:
        valid_faces.sort(key=lambda x: x[0], reverse=True)  # Sort by confidence descending
        return [valid_faces[0][1]]  # Return only best embedding

    # Return all embeddings (discard confidence scores)
    return [emb for _, emb in valid_faces]


def load_known_faces(
    known_root: str,
    min_face_size: int = 80,
    enable_augmentation: bool = True,
    det_thresh_known: float = 0.3,
    return_best_only: bool = False,
    return_per_file: bool = False,
) -> tuple[dict[str, list[np.ndarray]] | dict[str, list[tuple[str, list[np.ndarray]]]], list[str]]:
    """
    Load known faces from directory with optional augmentation.

    Args:
        known_root: Path to directory containing person subdirectories
        min_face_size: Minimum face size in pixels
        enable_augmentation: Apply conservative augmentation (flip + brightness ±20%).
                           Default True. Improves TPR from 77.5% to 82.5% while
                           maintaining 0.0% FPR.
        det_thresh_known: Detection confidence threshold for known_people images (0.0-1.0).
                         Lower than det_thresh for test images because we assume faces exist.
        return_best_only: If True, use only highest confidence face per image (handles multi-person photos)
        return_per_file: If True, return per-file metadata {person: [(filename, [embeddings])]}
                        instead of flattened {person: [embeddings]}. Useful for LOOCV.

    Returns:
        (encodings_dict, people_list) where:
        - If return_per_file=False: encodings_dict = {person: [embeddings]}
        - If return_per_file=True: encodings_dict = {person: [(filename, [embeddings])]}
        - people_list: list of person names
    """
    app = _get_app(det_thresh=det_thresh_known)
    people: list[str] = []
    valid_extensions = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

    if return_per_file:
        # Return per-file structure: {person: [(filename, [embeddings])]}
        encodings_per_file: dict[str, list[tuple[str, list[np.ndarray]]]] = {}

        for person_dir in Path(known_root).iterdir():
            if not person_dir.is_dir():
                continue
            person = person_dir.name
            people.append(person)
            encodings_per_file[person] = []

            for img_path in person_dir.glob("*.*"):
                # Skip Zone.Identifier and other non-image files
                if (
                    "Zone.Identifier" in img_path.name
                    or img_path.suffix.lower() not in valid_extensions
                ):
                    continue

                try:
                    # Load image as PIL Image for augmentation
                    img_pil = Image.open(img_path).convert("RGB")
                except Exception:
                    continue

                # Apply augmentation if enabled
                if enable_augmentation:
                    from dmaf.face_recognition.augmentation import (
                        apply_conservative_augmentation,
                    )

                    augmented_images = apply_conservative_augmentation(img_pil)
                else:
                    augmented_images = [("original", np.array(img_pil))]

                # Extract face encodings from original + augmented versions
                file_embeddings = []
                for _aug_name, img_np in augmented_images:
                    embs = _embed_faces(
                        app, img_np, min_face_size, return_best_only=return_best_only
                    )
                    file_embeddings.extend(embs)

                # Store with filename
                if file_embeddings:
                    encodings_per_file[person].append((img_path.name, file_embeddings))

        return encodings_per_file, people
    else:
        # Return flattened structure: {person: [embeddings]}
        encodings: dict[str, list[np.ndarray]] = {}

        for person_dir in Path(known_root).iterdir():
            if not person_dir.is_dir():
                continue
            person = person_dir.name
            people.append(person)
            encodings[person] = []

            for img_path in person_dir.glob("*.*"):
                # Skip Zone.Identifier and other non-image files
                if (
                    "Zone.Identifier" in img_path.name
                    or img_path.suffix.lower() not in valid_extensions
                ):
                    continue

                try:
                    # Load image as PIL Image for augmentation
                    img_pil = Image.open(img_path).convert("RGB")
                except Exception:
                    continue

                # Apply augmentation if enabled
                if enable_augmentation:
                    from dmaf.face_recognition.augmentation import (
                        apply_conservative_augmentation,
                    )

                    augmented_images = apply_conservative_augmentation(img_pil)
                else:
                    augmented_images = [("original", np.array(img_pil))]

                # Extract face encodings from original + augmented versions
                for _aug_name, img_np in augmented_images:
                    embs = _embed_faces(
                        app, img_np, min_face_size, return_best_only=return_best_only
                    )
                    encodings[person].extend(embs)

        return encodings, people


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    # inputs are expected normalized, but guard anyway
    a = a / max(np.linalg.norm(a), 1e-6)
    b = b / max(np.linalg.norm(b), 1e-6)
    return float(np.dot(a, b))


def best_match(
    known: dict[str, list[np.ndarray]],
    img_rgb: np.ndarray,
    tolerance: float = 0.40,
    min_face_size: int = 80,
    det_thresh: float = 0.4,
    return_best_only: bool = False,
) -> tuple[bool, list[str]]:
    """
    Find matching faces in an image using InsightFace.

    Args:
        known: Dictionary mapping person names to face encodings
        img_rgb: Image as numpy array in RGB format (from PIL Image.open().convert("RGB"))
        tolerance: Cosine distance threshold (lower = stricter, typical: 0.3-0.5)
        min_face_size: Minimum face size in pixels
        det_thresh: Detection confidence threshold (0.0-1.0)
        return_best_only: If True and multiple faces detected, use only highest confidence face

    Returns: (any_match, list_of_matched_people)
    """
    app = _get_app(det_thresh=det_thresh)
    # InsightFace expects RGB input, which is what PIL provides
    # No channel reversal needed!
    test_embs = _embed_faces(app, img_rgb, min_face_size, return_best_only=return_best_only)
    if not test_embs:
        return False, []
    matches = set()
    for e in test_embs:
        for person, plist in known.items():
            if not plist:
                continue
            # cosine similarity threshold on normalized embeddings
            if any(_cosine_sim(e, k) >= (1.0 - tolerance) for k in plist):
                matches.add(person)
    return (len(matches) > 0), sorted(matches)
