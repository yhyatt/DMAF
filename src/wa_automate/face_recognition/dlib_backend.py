# face index logic
from pathlib import Path

import face_recognition
import numpy as np


def load_known_faces(known_root: str) -> tuple[dict[str, list[np.ndarray]], list[str]]:
    """
    Returns: dict person -> list of 128-d encodings, and flat list of person names
    """
    encodings: dict[str, list[np.ndarray]] = {}
    people = []
    valid_extensions = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

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
                img = face_recognition.load_image_file(str(img_path))
            except Exception:
                # Skip files that can't be loaded as images
                continue
            locs = face_recognition.face_locations(
                img, model="hog"
            )  # or "cnn" if you have GPU/CUDA build
            if not locs:
                continue
            encs = face_recognition.face_encodings(img, locs)
            encodings[person].extend(encs)
    return encodings, people


def best_match(
    known: dict[str, list[np.ndarray]],
    img_rgb: np.ndarray,
    tolerance: float = 0.52,
    min_face_size: int = 80,
) -> tuple[bool, list[str]]:
    """
    Find matching faces in an image.

    Args:
        known: Dictionary mapping person names to face encodings
        img_rgb: Image as numpy array in RGB format (from PIL Image.open().convert("RGB"))
        tolerance: Matching threshold (lower = stricter, typical: 0.5-0.6)
        min_face_size: Minimum face size in pixels

    Returns: (any_match, list_of_matched_people)
    """
    # face_recognition expects RGB input, which is what PIL provides
    # No channel reversal needed!
    locs = face_recognition.face_locations(img_rgb, model="hog")
    # Optionally filter tiny boxes
    locs = [b for b in locs if (b[2] - b[0]) >= min_face_size and (b[1] - b[3]) >= min_face_size]
    if not locs:
        return False, []
    encs = face_recognition.face_encodings(img_rgb, locs)
    matches = set()
    for enc in encs:
        for person, plist in known.items():
            if not plist:
                continue
            results = face_recognition.compare_faces(plist, enc, tolerance=tolerance)
            if any(results):
                matches.add(person)
    return (len(matches) > 0), sorted(matches)
