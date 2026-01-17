#!/usr/bin/env python3
"""
Benchmark face recognition backends (face_recognition, insightface, auraface).

Compares accuracy (TPR, FPR) and performance (load time, encoding speed)
using Leave-One-Out Cross-Validation on real test data.
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dmaf.face_recognition import factory


def benchmark_loocv_accuracy(
    known_people_path: Path,
    backend_name: str,
    min_face_size: int = 80,
) -> dict:
    """
    Leave-one-out cross-validation for same-person matching (TPR).

    For each person:
      For each image I:
        Train: Use all OTHER images as known encodings
        Test: Try to match image I
        Record: Did it correctly identify the person?

    Args:
        known_people_path: Path to known_people directory
        backend_name: 'face_recognition', 'insightface', or 'auraface'
        min_face_size: Minimum face size in pixels

    Returns:
        Dictionary with results: {
            'correct': int,
            'incorrect': int,
            'total': int,
            'tpr': float,
        }
    """
    results = {"correct": 0, "incorrect": 0, "total": 0}
    tolerance = (
        0.55 if backend_name == "face_recognition" else 0.42
    )  # InsightFace/AuraFace use 0.42

    person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]

    print(f"\n{'=' * 80}")
    print(f"LOOCV ACCURACY BENCHMARK: {backend_name}")
    print(f"{'=' * 80}")
    print(f"Testing {len(person_dirs)} people")
    print(f"Tolerance: {tolerance}")
    print(f"Min face size: {min_face_size}px")
    print(f"{'=' * 80}")
    print("\nPhase 1: Loading all embeddings from full directory...")

    # Load entire directory once with per-file metadata (matches production)
    all_person_embeddings_with_paths, _ = factory.load_known_faces(
        str(known_people_path),
        backend_name=backend_name,
        min_face_size=min_face_size,
        return_per_file=True,
    )

    print(f"✓ Loaded embeddings for {len(all_person_embeddings_with_paths)} people")

    # Convert to full path mapping for LOOCV
    all_person_embeddings = {}
    for person_name, file_list in all_person_embeddings_with_paths.items():
        person_dir = known_people_path / person_name
        images = sorted(list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png")))

        if len(images) < 2:
            print(f"⚠️  Skipping {person_name}: needs at least 2 images for LOOCV")
            continue

        # Build mapping: filename -> embeddings
        filename_to_embeddings = {filename: embeddings for filename, embeddings in file_list}

        # Create list of (full_path, embeddings) for LOOCV
        all_person_embeddings[person_name] = []
        for img_path in images:
            if img_path.name in filename_to_embeddings:
                all_person_embeddings[person_name].append(
                    (img_path, filename_to_embeddings[img_path.name])
                )

    print("\nPhase 2: Running LOOCV with pre-computed embeddings...\n")

    # Run LOOCV using pre-computed embeddings
    for person_idx, person_name in enumerate(sorted(all_person_embeddings.keys()), 1):
        img_embeddings_list = all_person_embeddings[person_name]
        print(
            f"Person {person_idx}/{len(all_person_embeddings)}: {person_name} ({len(img_embeddings_list)} images)"
        )

        # LOOCV: For each image, train on N-1, test on 1
        for test_idx, (test_img_path, _) in enumerate(img_embeddings_list):
            print(
                f"  LOOCV {test_idx + 1}/{len(img_embeddings_list)}: {test_img_path.name}...",
                end=" ",
                flush=True,
            )

            # Build training encodings with ALL people (excluding only test image)
            # CRITICAL: Must include all people to match production behavior where
            # best_match() can match to any known person, not just the target person
            encodings = {}
            for p_name, p_img_list in all_person_embeddings.items():
                encodings[p_name] = []
                for idx, (img_path, img_embeddings) in enumerate(p_img_list):
                    # Skip test image only if this is the current person being tested
                    if p_name == person_name and idx == test_idx:
                        continue
                    encodings[p_name].extend(img_embeddings)

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

            results["total"] += 1

            if matched and person_name in who:
                results["correct"] += 1
                print("✓ MATCH")
            else:
                results["incorrect"] += 1
                print(f"✗ NO MATCH (got: {who if matched else 'no face'})")

        print()

    # Calculate TPR
    if results["total"] > 0:
        results["tpr"] = results["correct"] / results["total"]

    return results


def benchmark_fpr(
    known_people_path: Path,
    unknown_people_path: Path,
    backend_name: str,
    min_face_size: int = 80,
) -> dict:
    """
    Test false positive rate (FPR) with unknown people.

    Args:
        known_people_path: Path to known_people directory
        unknown_people_path: Path to unknown_people directory
        backend_name: 'face_recognition', 'insightface', or 'auraface'
        min_face_size: Minimum face size in pixels

    Returns:
        Dictionary with results: {
            'false_positives': int,
            'true_negatives': int,
            'no_face': int,
            'total': int,
            'fpr': float,
        }
    """
    print(f"\n{'=' * 80}")
    print(f"FALSE POSITIVE RATE BENCHMARK: {backend_name}")
    print(f"{'=' * 80}")

    # Load ALL known people encodings
    known_encodings, _ = factory.load_known_faces(
        str(known_people_path), backend_name=backend_name, min_face_size=min_face_size
    )

    results = {"false_positives": 0, "true_negatives": 0, "no_face": 0, "total": 0}
    tolerance = (
        0.55 if backend_name == "face_recognition" else 0.42
    )  # InsightFace/AuraFace use 0.42

    # Test each unknown person image
    unknown_images = list(unknown_people_path.glob("*.jpg")) + list(
        unknown_people_path.glob("*.png")
    )

    if not unknown_images:
        print("⚠️  No unknown images found")
        return None

    print(f"Testing {len(unknown_images)} unknown people images...")
    print(f"Tolerance: {tolerance}\n")

    for i, unknown_img_path in enumerate(unknown_images, 1):
        if i % 20 == 0:
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

    # Calculate FPR
    if results["total"] > 0:
        results["fpr"] = results["false_positives"] / results["total"]

    return results


def benchmark_performance(backend_name: str, known_people_path: Path) -> dict:
    """
    Measure performance metrics (load time, encoding speed).

    Args:
        backend_name: 'face_recognition' or 'insightface'
        known_people_path: Path to known_people directory

    Returns:
        Dictionary with results: {
            'load_time_ms': float,
            'encoding_time_ms': float,
        }
    """
    print(f"\n{'=' * 80}")
    print(f"PERFORMANCE BENCHMARK: {backend_name}")
    print(f"{'=' * 80}\n")

    # Measure model load time
    if backend_name == "insightface":
        import dmaf.face_recognition.insightface_backend as ib

        ib._app_cache.clear()

    start = time.time()

    if backend_name == "face_recognition":
        import face_recognition

        dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
        face_recognition.face_locations(dummy_img)
    else:
        import dmaf.face_recognition.insightface_backend as ib

        _ = ib._get_app()

    load_time_ms = (time.time() - start) * 1000
    print(f"Model load time: {load_time_ms:.0f}ms")

    # Measure encoding time
    person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]
    test_img_path = None
    for person_dir in person_dirs:
        images = list(person_dir.glob("*.jpg"))
        if images:
            test_img_path = images[0]
            break

    if test_img_path:
        img = Image.open(test_img_path).convert("RGB")
        img_np = np.array(img)

        # Warm up
        factory.best_match({}, img_np, backend_name=backend_name)

        # Measure
        start = time.time()
        factory.best_match({}, img_np, backend_name=backend_name)
        encoding_time_ms = (time.time() - start) * 1000
        print(f"Encoding time: {encoding_time_ms:.1f}ms per image")
    else:
        encoding_time_ms = None
        print("⚠️  No test images found for encoding benchmark")

    return {
        "load_time_ms": load_time_ms,
        "encoding_time_ms": encoding_time_ms,
    }


def print_comparison(results: dict):
    """Print comparison table for all backends."""
    print("\n" + "=" * 80)
    print("BACKEND COMPARISON SUMMARY")
    print("=" * 80)
    print(f"{'Backend':<20} {'TPR':<10} {'FPR':<10} {'Load (ms)':<12} {'Encode (ms)':<12}")
    print("-" * 80)

    for backend_name, data in results.items():
        tpr_str = f"{data['tpr']:.2%}" if "tpr" in data else "N/A"
        fpr_str = f"{data['fpr']:.2%}" if "fpr" in data else "N/A"
        load_str = f"{data['load_time_ms']:.0f}" if "load_time_ms" in data else "N/A"
        encode_str = f"{data['encoding_time_ms']:.1f}" if data.get("encoding_time_ms") else "N/A"

        print(f"{backend_name:<20} {tpr_str:<10} {fpr_str:<10} {load_str:<12} {encode_str:<12}")

    print("=" * 80)

    # Print recommendation
    print("\nRECOMMENDATIONS:")

    # Find best TPR and FPR
    best_tpr_backend = max(results.items(), key=lambda x: x[1].get("tpr", 0))
    best_fpr_backend = min(results.items(), key=lambda x: x[1].get("fpr", 1))

    print(f"  Best accuracy (TPR): {best_tpr_backend[0]} ({best_tpr_backend[1].get('tpr', 0):.2%})")
    print(
        f"  Best precision (FPR): {best_fpr_backend[0]} ({best_fpr_backend[1].get('fpr', 0):.2%})"
    )

    # Speed comparison
    if "insightface" in results and "face_recognition" in results:
        if results["insightface"].get("encoding_time_ms") and results["face_recognition"].get(
            "encoding_time_ms"
        ):
            speedup = (
                results["face_recognition"]["encoding_time_ms"]
                / results["insightface"]["encoding_time_ms"]
            )
            print(f"  Speed: insightface is {speedup:.1f}x faster than face_recognition")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark face recognition backends")
    parser.add_argument(
        "--known-people",
        type=Path,
        default=Path("data/known_people"),
        help="Path to known_people directory (default: data/known_people)",
    )
    parser.add_argument(
        "--unknown-people",
        type=Path,
        default=Path("data/unknown_people"),
        help="Path to unknown_people directory for FPR testing (default: data/unknown_people)",
    )
    parser.add_argument(
        "--backends",
        nargs="+",
        choices=["face_recognition", "insightface", "auraface"],
        default=["face_recognition", "insightface", "auraface"],
        help="Backends to benchmark (default: all)",
    )
    parser.add_argument(
        "--min-face-size",
        type=int,
        default=80,
        help="Minimum face size in pixels (default: 80)",
    )
    parser.add_argument(
        "--skip-loocv",
        action="store_true",
        help="Skip LOOCV accuracy test (slow)",
    )
    parser.add_argument(
        "--skip-fpr",
        action="store_true",
        help="Skip FPR test (requires unknown_people directory)",
    )
    parser.add_argument(
        "--skip-performance",
        action="store_true",
        help="Skip performance benchmarks",
    )

    args = parser.parse_args()

    if not args.known_people.exists():
        print(f"Error: known_people directory not found: {args.known_people}")
        sys.exit(1)

    print("=" * 80)
    print("FACE RECOGNITION BACKEND BENCHMARK")
    print("=" * 80)
    print(f"Known people: {args.known_people}")
    print(f"Unknown people: {args.unknown_people}")
    print(f"Backends: {', '.join(args.backends)}")
    print(f"Min face size: {args.min_face_size}px")
    print("=" * 80)

    all_results = {}

    for backend_name in args.backends:
        backend_results = {}

        # LOOCV accuracy test
        if not args.skip_loocv:
            loocv_results = benchmark_loocv_accuracy(
                args.known_people,
                backend_name,
                args.min_face_size,
            )
            backend_results.update(loocv_results)

            print(f"\n{backend_name} LOOCV Results:")
            print(f"  Total tests: {loocv_results['total']}")
            print(f"  Correct: {loocv_results['correct']}")
            print(f"  Incorrect: {loocv_results['incorrect']}")
            print(f"  TPR: {loocv_results['tpr']:.2%}")

        # FPR test
        if not args.skip_fpr and args.unknown_people.exists():
            fpr_results = benchmark_fpr(
                args.known_people,
                args.unknown_people,
                backend_name,
                args.min_face_size,
            )
            if fpr_results:
                backend_results.update(fpr_results)

                print(f"\n{backend_name} FPR Results:")
                print(f"  Total tests: {fpr_results['total']}")
                print(
                    f"  True Negatives: {fpr_results['true_negatives']} ({fpr_results['no_face']} no-face)"
                )
                print(f"  False Positives: {fpr_results['false_positives']}")
                print(f"  FPR: {fpr_results['fpr']:.2%}")

        # Performance benchmarks
        if not args.skip_performance:
            perf_results = benchmark_performance(backend_name, args.known_people)
            backend_results.update(perf_results)

        all_results[backend_name] = backend_results

    # Print comparison table
    if len(args.backends) > 1:
        print_comparison(all_results)

    print("\nBENCHMARK COMPLETE")
