# face_index.py (InsightFace backend)
from pathlib import Path
from typing import Dict, List, Tuple
import threading
import numpy as np
from PIL import Image
import insightface
from insightface.app import FaceAnalysis

# Thread-safe singleton for FaceAnalysis model
_app_lock = threading.Lock()
_app_instance = None


def _get_app() -> FaceAnalysis:
    """
    Get or initialize the FaceAnalysis model instance.

    Uses thread-safe singleton pattern to avoid reloading the model on every call.
    The model is ~600MB and takes several seconds to load, so caching is critical.
    """
    global _app_instance

    if _app_instance is None:
        with _app_lock:
            # Double-check locking pattern
            if _app_instance is None:
                app = FaceAnalysis(name="buffalo_l")  # balanced accuracy/speed (ResNet-50, 99.7% LFW)
                # ctx_id=-1 = CPU; set 0 if you configured CUDA in WSL
                # det_thresh=0.4 lowers detection confidence slightly for better recall
                # (default 0.5 was missing some faces, but 0.35 was too permissive)
                # Keep det_size=(640, 640) - larger sizes need proportionally larger min_face_size
                app.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.4)
                _app_instance = app

    return _app_instance

def _img_to_np(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))

def _embed_faces(app: FaceAnalysis, img_np: np.ndarray, min_face: int) -> List[np.ndarray]:
    faces = app.get(img_np)
    # filter tiny detections
    out = []
    for f in faces:
        x1, y1, x2, y2 = map(int, f.bbox)
        if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
            # normed_embedding is already L2-normalized
            out.append(f.normed_embedding.astype(np.float32))
    return out

def load_known_faces(
    known_root: str,
    min_face_size: int = 80,
    enable_augmentation: bool = True
) -> Tuple[Dict[str, List[np.ndarray]], List[str]]:
    """
    Load known faces from directory with optional augmentation.

    Args:
        known_root: Path to directory containing person subdirectories
        min_face_size: Minimum face size in pixels
        enable_augmentation: Apply conservative augmentation (flip + brightness ±20%).
                           Default True. Improves TPR from 77.5% to 82.5% while
                           maintaining 0.0% FPR.

    Returns:
        (encodings_dict, people_list) where encodings_dict maps person names to
        face encodings, and people_list is the list of person names.
    """
    app = _get_app()
    encodings: Dict[str, List[np.ndarray]] = {}
    people: List[str] = []
    valid_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.webp'}

    for person_dir in Path(known_root).iterdir():
        if not person_dir.is_dir():
            continue
        person = person_dir.name
        people.append(person)
        encodings[person] = []

        for img_path in person_dir.glob("*.*"):
            # Skip Zone.Identifier and other non-image files
            if 'Zone.Identifier' in img_path.name or img_path.suffix.lower() not in valid_extensions:
                continue

            try:
                # Load image as PIL Image for augmentation
                img_pil = Image.open(img_path).convert("RGB")
            except Exception:
                continue

            # Apply augmentation if enabled
            if enable_augmentation:
                from wa_automate.face_recognition.augmentation import apply_conservative_augmentation
                augmented_images = apply_conservative_augmentation(img_pil)
            else:
                augmented_images = [("original", np.array(img_pil))]

            # Extract face encodings from original + augmented versions
            for aug_name, img_np in augmented_images:
                embs = _embed_faces(app, img_np, min_face_size)
                encodings[person].extend(embs)

    return encodings, people

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    # inputs are expected normalized, but guard anyway
    a = a / max(np.linalg.norm(a), 1e-6)
    b = b / max(np.linalg.norm(b), 1e-6)
    return float(np.dot(a, b))

def best_match(known: Dict[str, List[np.ndarray]],
               img_rgb: np.ndarray,
               tolerance: float = 0.40,
               min_face_size: int = 80) -> Tuple[bool, List[str]]:
    """
    Find matching faces in an image using InsightFace.

    Args:
        known: Dictionary mapping person names to face encodings
        img_rgb: Image as numpy array in RGB format (from PIL Image.open().convert("RGB"))
        tolerance: Cosine distance threshold (lower = stricter, typical: 0.3-0.5)
        min_face_size: Minimum face size in pixels

    Returns: (any_match, list_of_matched_people)
    """
    app = _get_app()
    # InsightFace expects RGB input, which is what PIL provides
    # No channel reversal needed!
    test_embs = _embed_faces(app, img_rgb, min_face_size)
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
