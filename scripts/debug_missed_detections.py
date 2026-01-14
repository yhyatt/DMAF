#!/usr/bin/env python3
"""Debug script to analyze missed face detections (no-face failures).

Usage:
    python scripts/debug_missed_detections.py

This script runs LOOCV on the known_people dataset and identifies which images
fail face detection (the 17.5% failure rate with conservative augmentation).

Outputs:
- List of all failed detections with details
- Statistics by person
- Recommendations for improving detection rate
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dmaf.face_recognition import factory


def analyze_missed_detections(
    known_people_path: Path,
    backend_name: str = "insightface",
    tolerance: float = 0.42,
    min_face_size: int = 80,
    enable_augmentation: bool = True,
) -> None:
    """
    Run LOOCV and identify all missed detections.

    Args:
        known_people_path: Path to data/known_people directory
        backend_name: Backend to use (default: insightface)
        tolerance: Matching tolerance
        min_face_size: Minimum face size in pixels
        enable_augmentation: Whether to use augmentation (default: True)
    """
    print("=" * 80)
    print("MISSED DETECTION ANALYSIS")
    print("=" * 80)
    print(f"Backend: {backend_name}")
    print(f"Augmentation: {'Enabled (conservative)' if enable_augmentation else 'Disabled'}")
    print(f"Tolerance: {tolerance}")
    print(f"Min face size: {min_face_size}px")
    print("=" * 80)
    print()

    # Collect all failures
    failures = []
    total_tests = 0
    person_stats = {}

    person_dirs = sorted([d for d in known_people_path.iterdir() if d.is_dir()])

    for person_idx, person_dir in enumerate(person_dirs, 1):
        person_name = person_dir.name
        images = sorted(list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png")))

        if len(images) < 2:
            continue

        person_stats[person_name] = {"total": len(images), "failures": [], "matches": []}

        print(f"Person {person_idx}/{len(person_dirs)}: {person_name} ({len(images)} images)")

        # LOOCV: For each image, train on N-1, test on 1
        for test_idx, test_img_path in enumerate(images):
            total_tests += 1

            # Build training set (all images EXCEPT test image)
            train_img_paths = [img for j, img in enumerate(images) if j != test_idx]

            # Load encodings using factory (respects augmentation setting)
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
                encodings, _ = factory.load_known_faces(
                    str(tmp_path),
                    backend_name=backend_name,
                    min_face_size=min_face_size,
                    enable_augmentation=enable_augmentation,
                )

                # Test held-out image
                test_img = Image.open(test_img_path).convert("RGB")
                test_img_np = np.array(test_img)

                matched, who = factory.best_match(
                    encodings,
                    test_img_np,
                    backend_name=backend_name,
                    tolerance=tolerance,
                    min_face_size=min_face_size,
                )

                # Check result
                if matched and person_name in who:
                    person_stats[person_name]["matches"].append(test_img_path.name)
                    print(f"  ✓ {test_img_path.name}")
                elif not matched or who == []:
                    # NO FACE DETECTED - this is what we're debugging
                    person_stats[person_name]["failures"].append(test_img_path.name)
                    failures.append(
                        {
                            "person": person_name,
                            "image": test_img_path.name,
                            "path": str(test_img_path),
                            "reason": "No face detected",
                        }
                    )
                    print(f"  ✗ {test_img_path.name} - NO FACE DETECTED")
                else:
                    # Matched wrong person (rare)
                    person_stats[person_name]["failures"].append(test_img_path.name)
                    failures.append(
                        {
                            "person": person_name,
                            "image": test_img_path.name,
                            "path": str(test_img_path),
                            "reason": f"Matched wrong person: {who}",
                        }
                    )
                    print(f"  ✗ {test_img_path.name} - WRONG MATCH: {who}")

        print()

    # Print summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total tests: {total_tests}")
    print(f"Total failures: {len(failures)} ({len(failures) / total_tests * 100:.1f}%)")
    print()

    # Per-person breakdown
    print("FAILURES BY PERSON:")
    print("-" * 80)
    for person, stats in person_stats.items():
        failure_count = len(stats["failures"])
        total = stats["total"]
        failure_rate = failure_count / total * 100 if total > 0 else 0

        print(f"{person}:")
        print(f"  Total: {total} images")
        print(f"  Failures: {failure_count} ({failure_rate:.1f}%)")

        if stats["failures"]:
            print("  Failed images:")
            for img_name in stats["failures"]:
                print(f"    - {img_name}")
        print()

    # Detailed failure list
    if failures:
        print("=" * 80)
        print("DETAILED FAILURE LIST (FOR DEBUGGING)")
        print("=" * 80)
        for i, failure in enumerate(failures, 1):
            print(f"{i}. {failure['person']} / {failure['image']}")
            print(f"   Path: {failure['path']}")
            print(f"   Reason: {failure['reason']}")
            print()

        # Provide debugging suggestions
        print("=" * 80)
        print("DEBUGGING SUGGESTIONS")
        print("=" * 80)
        print()
        print("To debug individual failed images, you can:")
        print()
        print("1. Examine image quality:")
        print("   - Open failed images and check for:")
        print("     * Small face size (<80px after det_size scaling)")
        print("     * Extreme angles (profile, looking down/up)")
        print("     * Occlusions (hands, objects blocking face)")
        print("     * Motion blur or low lighting")
        print()
        print("2. Test detection parameters:")
        print("   from dmaf.face_recognition.insightface_backend import _get_app")
        print("   from PIL import Image")
        print("   import numpy as np")
        print()
        print("   app = _get_app()")
        print("   img = Image.open('/path/to/failed/image.jpg').convert('RGB')")
        print("   img_np = np.array(img)")
        print("   faces = app.get(img_np)")
        print("   print(f'Detected {len(faces)} faces')")
        print("   if faces:")
        print("       for face in faces:")
        print("           bbox = face.bbox  # [x1, y1, x2, y2]")
        print("           width = bbox[2] - bbox[0]")
        print("           height = bbox[3] - bbox[1]")
        print("           print(f'Face size: {width:.0f}x{height:.0f}px')")
        print()
        print("3. Try adjusting parameters:")
        print("   - Lower min_face_size (e.g., 60 or 40)")
        print("   - Lower det_thresh in insightface_backend.py (currently 0.4)")
        print("   - Increase det_size (currently 640x640, try 1280x1280)")
        print()
        print("4. Consider adding targeted augmentations:")
        print("   - For profile faces: Add larger rotation augmentations")
        print("   - For dark images: Add more aggressive brightness augmentation")
        print("   - For small faces: Resize images before encoding")
        print()

    else:
        print("🎉 NO FAILURES! All images detected successfully.")


if __name__ == "__main__":
    # Default paths
    project_root = Path(__file__).parent.parent
    known_people_path = project_root / "data" / "known_people"

    if not known_people_path.exists():
        print(f"Error: Known people directory not found: {known_people_path}")
        print("Please ensure data/known_people exists with person subdirectories.")
        sys.exit(1)

    # Run analysis with augmentation enabled (default)
    analyze_missed_detections(
        known_people_path=known_people_path,
        backend_name="insightface",
        tolerance=0.42,
        min_face_size=80,
        enable_augmentation=True,  # Conservative augmentation
    )

    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
