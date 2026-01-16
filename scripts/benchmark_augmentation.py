#!/usr/bin/env python3
"""
Benchmark different augmentation strategies for face recognition.

Compares various augmentation approaches (flip, brightness, rotation, etc.)
to determine their impact on recognition accuracy (TPR) using LOOCV.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dmaf.face_recognition import factory
from tests.augmentation_utils import (
    AUGMENTATION_STRATEGIES,
    apply_augmentations,
    get_strategy_description,
)


def benchmark_augmentation_strategy(
    known_people_path: Path,
    strategy_name: str,
    backend_name: str = "insightface",
    min_face_size: int = 80,
    tolerance: float = 0.42,
    det_thresh: float = 0.4,
) -> dict:
    """
    Benchmark a single augmentation strategy using LOOCV.

    Args:
        known_people_path: Path to known_people directory
        strategy_name: Name of augmentation strategy from AUGMENTATION_STRATEGIES
        backend_name: Face recognition backend to use
        min_face_size: Minimum face size in pixels
        tolerance: Matching tolerance
        det_thresh: Detection threshold

    Returns:
        Dictionary with results: {
            'correct': int,
            'incorrect': int,
            'total': int,
            'no_face': int,
            'training_samples': int,
            'tpr': float,
        }
    """
    augmentation_fns = AUGMENTATION_STRATEGIES[strategy_name]

    results = {
        "correct": 0,
        "incorrect": 0,
        "total": 0,
        "no_face": 0,
        "training_samples": 0,
    }

    person_dirs = [d for d in known_people_path.iterdir() if d.is_dir()]

    print(f"\n{'=' * 80}")
    print(f"Augmentation Strategy: {strategy_name}")
    print(f"Description: {get_strategy_description(strategy_name)}")
    print(f"Backend: {backend_name}")
    print(f"Testing {len(person_dirs)} people with LOOCV")
    print(f"{'=' * 80}\n")

    for person_idx, person_dir in enumerate(person_dirs, 1):
        person_name = person_dir.name
        images = list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png"))

        if len(images) < 2:
            print(f"⚠️  Skipping {person_name}: needs at least 2 images for LOOCV")
            continue

        print(f"Person {person_idx}/{len(person_dirs)}: {person_name} ({len(images)} images)")

        # LOOCV: For each image, train on N-1, test on 1
        for test_idx, test_img_path in enumerate(images):
            print(
                f"  LOOCV {test_idx + 1}/{len(images)}: {test_img_path.name}...",
                end=" ",
                flush=True,
            )

            # Build training encodings with ALL people (excluding only test image)
            # CRITICAL: Must include all people to match production behavior where
            # best_match() can match to any known person, not just the target person
            known = {}

            # First, add all OTHER people (not current person being tested)
            for other_dir in person_dirs:
                if other_dir.name == person_name:
                    continue  # Skip current person, we'll add them separately

                other_images = list(other_dir.glob("*.jpg")) + list(other_dir.glob("*.png"))
                other_encodings = []
                for other_img_path in other_images:
                    # Apply augmentations to other people's images
                    augmented_imgs = apply_augmentations(other_img_path, augmentation_fns)
                    for _, img_array in augmented_imgs:
                        if backend_name == "insightface":
                            from dmaf.face_recognition.insightface_backend import (
                                _embed_faces,
                                _get_app,
                            )

                            app = _get_app(det_thresh=det_thresh)
                            embs = _embed_faces(app, img_array, min_face_size)
                            other_encodings.extend(embs)
                        else:
                            raise ValueError(
                                f"Backend {backend_name} not supported for augmentation benchmarking"
                            )
                known[other_dir.name] = other_encodings

            # Now add current person's training images (excluding test image)
            train_img_paths = [img for j, img in enumerate(images) if j != test_idx]
            train_encodings = []
            for train_img_path in train_img_paths:
                # Get original + augmented versions
                augmented_imgs = apply_augmentations(train_img_path, augmentation_fns)
                results["training_samples"] += len(augmented_imgs)

                # Extract face encodings from each version
                for _, img_array in augmented_imgs:
                    # Use backend-specific embedding function
                    if backend_name == "insightface":
                        from dmaf.face_recognition.insightface_backend import (
                            _embed_faces,
                            _get_app,
                        )

                        app = _get_app(det_thresh=det_thresh)
                        embs = _embed_faces(app, img_array, min_face_size)
                        train_encodings.extend(embs)
                    else:
                        raise ValueError(
                            f"Backend {backend_name} not supported for augmentation benchmarking"
                        )
            known[person_name] = train_encodings

            # Test against original held-out image (no augmentation on test)
            test_img = Image.open(test_img_path).convert("RGB")
            test_img_np = np.array(test_img)

            matched, who = factory.best_match(
                known,
                test_img_np,
                backend_name=backend_name,
                tolerance=tolerance,
                min_face_size=min_face_size,
                det_thresh=det_thresh,
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

    # Calculate TPR
    if results["total"] > 0:
        results["tpr"] = results["correct"] / results["total"]
        results["avg_training_samples"] = results["training_samples"] / results["total"]

    return results


def print_results(strategy_name: str, results: dict):
    """Print formatted benchmark results."""
    print(f"\n{'=' * 80}")
    print(f"{strategy_name.upper()} - BENCHMARK RESULTS")
    print(f"{'=' * 80}")
    print(f"Strategy: {get_strategy_description(strategy_name)}")
    print(f"Total tests: {results['total']}")
    print(f"Correct: {results['correct']}")
    print(f"Incorrect: {results['incorrect']} ({results['no_face']} no-face)")
    print(f"TPR (True Positive Rate): {results['tpr']:.2%}")
    print(f"Avg training samples per test: {results['avg_training_samples']:.1f}")
    print(f"{'=' * 80}\n")


def compare_strategies(known_people_path: Path, strategies: list[str], **kwargs):
    """
    Compare multiple augmentation strategies and print comparison table.

    Args:
        known_people_path: Path to known_people directory
        strategies: List of strategy names to benchmark
        **kwargs: Additional arguments passed to benchmark_augmentation_strategy
    """
    all_results = {}

    for strategy_name in strategies:
        results = benchmark_augmentation_strategy(known_people_path, strategy_name, **kwargs)
        all_results[strategy_name] = results
        print_results(strategy_name, results)

    # Print comparison table
    print("\n" + "=" * 80)
    print("COMPARISON TABLE")
    print("=" * 80)
    print(f"{'Strategy':<20} {'TPR':<10} {'Avg Samples':<15} {'Description':<30}")
    print("-" * 80)

    # Sort by TPR descending
    sorted_strategies = sorted(all_results.items(), key=lambda x: x[1]["tpr"], reverse=True)

    for strategy_name, results in sorted_strategies:
        tpr_str = f"{results['tpr']:.2%}"
        samples_str = f"{results['avg_training_samples']:.1f}"
        desc = get_strategy_description(strategy_name)
        print(f"{strategy_name:<20} {tpr_str:<10} {samples_str:<15} {desc:<30}")

    print("=" * 80)

    # Print recommendations
    baseline_tpr = all_results["none"]["tpr"]
    best_strategy, best_results = sorted_strategies[0]

    print("\nRECOMMENDATIONS:")
    print(f"  Baseline (no augmentation): {baseline_tpr:.2%} TPR")
    print(f"  Best strategy: {best_strategy} ({best_results['tpr']:.2%} TPR)")

    if best_results["tpr"] > baseline_tpr:
        improvement = (best_results["tpr"] - baseline_tpr) * 100
        print(f"  Improvement: +{improvement:.1f}% absolute TPR gain")
        print(f"  ✅ Augmentation recommended: Use '{best_strategy}' strategy")
    else:
        print("  ⚠️  No improvement over baseline - consider disabling augmentation")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark augmentation strategies for face recognition"
    )
    parser.add_argument(
        "--known-people",
        type=Path,
        default=Path("data/known_people"),
        help="Path to known_people directory (default: data/known_people)",
    )
    parser.add_argument(
        "--backend",
        choices=["insightface"],
        default="insightface",
        help="Face recognition backend (default: insightface)",
    )
    parser.add_argument(
        "--min-face-size",
        type=int,
        default=80,
        help="Minimum face size in pixels (default: 80)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.42,
        help="Matching tolerance (default: 0.42)",
    )
    parser.add_argument(
        "--det-thresh",
        type=float,
        default=0.4,
        help="Detection threshold (default: 0.4)",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=list(AUGMENTATION_STRATEGIES.keys()),
        default=None,
        help="Strategies to benchmark (default: all)",
    )

    args = parser.parse_args()

    if not args.known_people.exists():
        print(f"Error: known_people directory not found: {args.known_people}")
        sys.exit(1)

    # Default: benchmark all strategies
    strategies = args.strategies or list(AUGMENTATION_STRATEGIES.keys())

    # Always include baseline for comparison
    if "none" not in strategies:
        strategies = ["none"] + strategies

    print("=" * 80)
    print("AUGMENTATION STRATEGY BENCHMARK")
    print("=" * 80)
    print(f"Known people directory: {args.known_people}")
    print(f"Backend: {args.backend}")
    print(f"Min face size: {args.min_face_size}px")
    print(f"Tolerance: {args.tolerance}")
    print(f"Detection threshold: {args.det_thresh}")
    print(f"Strategies to test: {', '.join(strategies)}")
    print("=" * 80)

    compare_strategies(
        args.known_people,
        strategies,
        backend_name=args.backend,
        min_face_size=args.min_face_size,
        tolerance=args.tolerance,
        det_thresh=args.det_thresh,
    )

    print("\nBENCHMARK COMPLETE")
