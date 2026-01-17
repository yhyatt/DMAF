#!/usr/bin/env python3
"""Debug script to analyze missed face detections using PRODUCTION settings.

Usage:
    python scripts/debug_missed_detections.py
    python scripts/debug_missed_detections.py --config custom_config.yaml
    python scripts/debug_missed_detections.py --det-thresh-known 0.3
    python scripts/debug_missed_detections.py --output-dir ./debug_output
    python scripts/debug_missed_detections.py --clear-cache  # Recommended for consistent results

This script runs LOOCV on the known_people dataset using the EXACT same settings
as production: config file, caching, parameters, etc.

IMPORTANT: Use --clear-cache when testing parameter changes (det_thresh, tolerance, etc.)
to ensure stale cached embeddings don't affect results.

Outputs:
- List of all failed detections with details
- Statistics by person
- Recommendations for improving detection rate
- Optional visualizations (--output-dir):
  - Phase 1 (Detection): Bounding boxes + detection scores on known_people images
  - Phase 2 (Recognition): Bounding boxes + similarity scores for all known people on test images
"""

import argparse
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Suppress ONNX Runtime warnings about CUDA not being available
warnings.filterwarnings("ignore", category=UserWarning, module="onnxruntime")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dmaf.config import Settings
from dmaf.database import get_database
from dmaf.face_recognition import factory

logger = logging.getLogger(__name__)

# Backend-specific imports will be done at runtime based on config
_cosine_sim = None
_get_app = None


def compute_all_similarities(
    test_embeddings: list[np.ndarray],
    known_encodings: dict[str, list[np.ndarray]],
) -> dict[str, float]:
    """
    Compute similarity scores between test embeddings and all known people.

    Args:
        test_embeddings: List of embeddings from test image
        known_encodings: Dict mapping person names to their face encodings

    Returns:
        Dict of {person_name: best_similarity_score}
    """
    similarities = {}
    for person_name, person_embeddings in known_encodings.items():
        if not person_embeddings:
            continue

        # Find best similarity across all test embeddings vs all person embeddings
        best_sim = 0.0
        for test_emb in test_embeddings:
            for known_emb in person_embeddings:
                sim = _cosine_sim(test_emb, known_emb)
                best_sim = max(best_sim, sim)

        similarities[person_name] = best_sim

    return similarities


def visualize_detections(
    img_path: Path,
    output_path: Path,
    faces: list,
    chosen_face_idx: int | None = None,
    title: str = "",
) -> None:
    """
    Visualize detected faces with bounding boxes and scores.

    Args:
        img_path: Path to input image
        output_path: Path to save visualization
        faces: List of face detection results from InsightFace (each with .bbox, .det_score)
        chosen_face_idx: Index of the face actually chosen (highlighted in bold)
        title: Optional title to overlay on image
    """
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Adaptive font sizing based on image resolution
    img_size = max(img.width, img.height)
    title_font_size = max(20, int(img_size / 40))  # ~2.5% of image dimension
    label_font_size = max(16, int(img_size / 50))  # ~2% of image dimension

    try:
        title_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", title_font_size
        )
        label_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", label_font_size
        )
        label_font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", label_font_size
        )
    except:
        title_font = ImageFont.load_default()
        label_font = ImageFont.load_default()
        label_font_bold = ImageFont.load_default()

    # Draw title if provided
    if title:
        draw.text((10, 10), title, fill=(255, 255, 0), font=title_font)

    # Draw each detected face
    for idx, face in enumerate(faces):
        x1, y1, x2, y2 = map(int, face.bbox)
        score = face.det_score
        is_chosen = idx == chosen_face_idx

        # Draw rectangle (yellow/bold for chosen, green for others)
        box_color = (255, 255, 0) if is_chosen else (0, 255, 0)
        box_width = 5 if is_chosen else 3
        draw.rectangle([(x1, y1), (x2, y2)], outline=box_color, width=box_width)

        # Draw detection score (bold for chosen face)
        score_text = f"Det: {score:.3f}"
        if is_chosen:
            score_text = f"✓ CHOSEN: {score:.3f}"

        text_color = (255, 255, 0) if is_chosen else (0, 255, 0)
        text_font = label_font_bold if is_chosen else label_font

        # Add background for better readability
        bbox = draw.textbbox((x1, y1 - label_font_size - 10), score_text, font=text_font)
        draw.rectangle(bbox, fill=(0, 0, 0, 128))
        draw.text((x1, y1 - label_font_size - 10), score_text, fill=text_color, font=text_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)


def visualize_recognition(
    img_path: Path,
    output_path: Path,
    faces: list,
    per_face_match_scores: list[dict[str, float]] | None,
    matched_names: list[str],
    tolerance: float,
) -> None:
    """
    Visualize recognition results with bounding boxes and matching scores.

    Args:
        img_path: Path to input image
        output_path: Path to save visualization
        faces: List of face detection results from InsightFace
        per_face_match_scores: List of dicts (one per face) with {person_name: similarity_score}
        matched_names: List of matched person names
        tolerance: Matching tolerance (to show threshold line)
    """
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Adaptive font sizing based on image resolution
    img_size = max(img.width, img.height)
    large_font_size = max(30, int(img_size / 30))  # ~3.3% for warnings
    label_font_size = max(16, int(img_size / 50))  # ~2% for labels

    try:
        large_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", large_font_size
        )
        label_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", label_font_size
        )
        label_font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", label_font_size
        )
    except:
        large_font = ImageFont.load_default()
        label_font = ImageFont.load_default()
        label_font_bold = ImageFont.load_default()

    # Calculate matching threshold (cosine similarity threshold)
    match_threshold = 1.0 - tolerance

    if not faces or per_face_match_scores is None:
        # No detection - overlay large warning with background
        warning_text = "NO DETECTION"
        bbox = draw.textbbox((img.width // 2 - 150, img.height // 2), warning_text, font=large_font)
        draw.rectangle(bbox, fill=(0, 0, 0, 180))
        draw.text(
            (img.width // 2 - 150, img.height // 2),
            warning_text,
            fill=(255, 0, 0),
            font=large_font,
        )
    else:
        # Draw each detected face with its own matching scores
        for face_idx, (face, face_scores) in enumerate(zip(faces, per_face_match_scores)):
            x1, y1, x2, y2 = map(int, face.bbox)

            # Check if THIS face matched
            face_matched = any(
                person_name in matched_names and score >= match_threshold
                for person_name, score in face_scores.items()
            )

            # Draw rectangle (green if matched, red if not)
            color = (0, 255, 0) if face_matched else (255, 0, 0)
            draw.rectangle([(x1, y1), (x2, y2)], outline=color, width=3)

            # Draw face number if multiple faces
            if len(faces) > 1:
                face_label = f"Face #{face_idx + 1}"
                bbox = draw.textbbox(
                    (x1, y1 - label_font_size - 30), face_label, font=label_font_bold
                )
                draw.rectangle(bbox, fill=(0, 0, 0, 180))
                draw.text(
                    (x1, y1 - label_font_size - 30),
                    face_label,
                    fill=(255, 255, 0),
                    font=label_font_bold,
                )

            # Draw matching scores for THIS face's top 5 people
            y_offset = y2 + 5
            for person_name, score in sorted(face_scores.items(), key=lambda x: x[1], reverse=True)[
                :5
            ]:  # Top 5
                is_matched = person_name in matched_names and score >= match_threshold

                # Show if score is above or below threshold
                threshold_indicator = "✓" if score >= match_threshold else "✗"
                match_text = f"{threshold_indicator} {person_name}: {score:.3f}"

                # Color: green if matched, yellow if above threshold but not matched, white otherwise
                if is_matched:
                    text_color = (0, 255, 0)
                    text_font = label_font_bold
                elif score >= match_threshold:
                    text_color = (255, 255, 0)  # Above threshold but not the target person
                    text_font = label_font
                else:
                    text_color = (255, 255, 255)  # Below threshold
                    text_font = label_font

                # Add background for readability
                bbox = draw.textbbox((x1, y_offset), match_text, font=text_font)
                draw.rectangle(bbox, fill=(0, 0, 0, 128))
                draw.text((x1, y_offset), match_text, fill=text_color, font=text_font)
                y_offset += label_font_size + 5

            # Draw threshold reference line
            threshold_text = f"Threshold: {match_threshold:.3f}"
            bbox = draw.textbbox((x1, y_offset + 5), threshold_text, font=label_font)
            draw.rectangle(bbox, fill=(0, 0, 0, 180))
            draw.text((x1, y_offset + 5), threshold_text, fill=(128, 128, 128), font=label_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)


def test_unknown_people(
    settings: Settings,
    unknown_people_dir: Path,
    encodings: dict[str, list[np.ndarray]],
    det_thresh_test: float,
    return_best_test: bool,
    output_dir: Path | None = None,
) -> dict:
    """
    Test unknown people (not in known_people) to measure False Positive Rate.

    Args:
        settings: Production Settings instance from config.yaml
        unknown_people_dir: Directory containing images of unknown people
        encodings: Pre-computed encodings of ALL known people
        det_thresh_test: Detection threshold for test images
        return_best_test: Use only highest confidence face in test images
        output_dir: Optional directory to save visualization images (false positives only)

    Returns:
        Dictionary with FPR statistics: {
            'total': int,
            'false_positives': int,
            'true_negatives': int,
            'fpr': float,
            'false_positive_details': list
        }
    """
    # Declare globals for backend-specific functions
    global _get_app, _cosine_sim

    if not unknown_people_dir.exists():
        print(f"⚠️  Unknown people directory not found: {unknown_people_dir}")
        print("   Skipping false positive rate analysis")
        print("   To enable: Create directory and add images of people NOT in known_people/")
        return None

    print()
    print("=" * 80)
    print("PHASE 3: FALSE POSITIVE RATE ANALYSIS (UNKNOWN PEOPLE)")
    print("=" * 80)
    print(f"Testing images from: {unknown_people_dir}")
    print(f"Detection threshold: {det_thresh_test}")
    print(f"Return best only: {return_best_test}")
    print("-" * 80)

    # Collect all unknown images
    unknown_images = []
    for ext in ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"]:
        unknown_images.extend(unknown_people_dir.glob(f"**/{ext}"))

    if not unknown_images:
        print("⚠️  No images found in unknown_people directory")
        return None

    print(f"Found {len(unknown_images)} unknown images to test")
    print()

    false_positives = []
    true_negatives = []
    all_similarity_scores = []  # Collect all max similarity scores for statistics

    for img_idx, img_path in enumerate(sorted(unknown_images), 1):
        # Test this unknown image against ALL known people
        img = Image.open(img_path).convert("RGB")
        img_np = np.array(img)

        matched, who = factory.best_match(
            encodings,
            img_np,
            backend_name=settings.recognition.backend,
            tolerance=settings.recognition.tolerance,
            min_face_size=settings.recognition.min_face_size_pixels,
            det_thresh=det_thresh_test,
            return_best_only=return_best_test,
        )

        # For TN reporting, compute max similarity score
        max_score = 0.0
        max_score_person = None

        if settings.recognition.backend in ("insightface", "auraface"):
            # Import backend-specific functions if not already imported
            if _get_app is None:
                if settings.recognition.backend == "insightface":
                    from dmaf.face_recognition.insightface_backend import _cosine_sim, _get_app
                else:  # auraface
                    from dmaf.face_recognition.auraface_backend import _cosine_sim, _get_app

            # Run detection and compute similarities to show closest match
            app = _get_app(det_thresh=det_thresh_test)
            faces = app.get(img_np)

            if faces:
                min_face = settings.recognition.min_face_size_pixels
                for f in faces:
                    x1, y1, x2, y2 = map(int, f.bbox)
                    if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
                        face_embeddings = [f.normed_embedding.astype(np.float32)]
                        similarities = compute_all_similarities(face_embeddings, encodings)

                        # Find max similarity across all known people
                        for person_name, score in similarities.items():
                            if score > max_score:
                                max_score = score
                                max_score_person = person_name
                        break  # Only check first valid face (return_best_only logic)

        if matched and who:
            # FALSE POSITIVE - unknown person matched to a known person
            # Also collect this score for statistics
            if max_score_person:
                all_similarity_scores.append(max_score)

            false_positives.append(
                {
                    "image": img_path.name,
                    "path": str(img_path),
                    "matched_to": who,
                    "score": max_score if max_score_person else None,
                }
            )

            threshold = 1.0 - settings.recognition.tolerance
            score_info = (
                f" (score: {max_score:.3f}, threshold: {threshold:.3f})" if max_score_person else ""
            )
            print(
                f"  ✗ FP {img_idx}/{len(unknown_images)}: {img_path.name} → matched to {who}{score_info}"
            )

            # Save visualization for false positives ONLY
            if output_dir and settings.recognition.backend in ("insightface", "auraface"):
                fp_dir = output_dir / "3_false_positives"
                fp_dir.mkdir(parents=True, exist_ok=True)

                # Run detection to get face objects for visualization
                faces = app.get(img_np)

                # Filter by min_face_size and collect embeddings per face
                min_face = settings.recognition.min_face_size_pixels
                valid_faces = []
                per_face_embeddings = []
                for f in faces:
                    x1, y1, x2, y2 = map(int, f.bbox)
                    if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
                        valid_faces.append(f)
                        per_face_embeddings.append([f.normed_embedding.astype(np.float32)])

                # Compute similarity scores per face
                per_face_match_scores = None
                if per_face_embeddings:
                    per_face_match_scores = [
                        compute_all_similarities(face_embs, encodings)
                        for face_embs in per_face_embeddings
                    ]

                output_path = fp_dir / img_path.name
                visualize_recognition(
                    img_path,
                    output_path,
                    valid_faces,
                    per_face_match_scores,
                    who,
                    settings.recognition.tolerance,
                )
        else:
            # TRUE NEGATIVE - unknown person correctly NOT matched
            true_negatives.append(str(img_path))

            # Collect similarity score for statistics (only if face was detected)
            if max_score_person:
                all_similarity_scores.append(max_score)

            # Show closest match score for analysis
            if max_score_person:
                threshold = 1.0 - settings.recognition.tolerance
                print(
                    f"  ✓ TN {img_idx}/{len(unknown_images)}: {img_path.name} → correctly rejected "
                    f"(closest: {max_score_person} {max_score:.3f}, threshold: {threshold:.3f})"
                )
            else:
                print(
                    f"  ✓ TN {img_idx}/{len(unknown_images)}: {img_path.name} → correctly rejected (no face detected)"
                )

    # Calculate FPR
    total = len(unknown_images)
    fp_count = len(false_positives)
    tn_count = len(true_negatives)
    fpr = fp_count / total if total > 0 else 0.0

    # Print summary
    print()
    print("-" * 80)
    print("FALSE POSITIVE RATE SUMMARY:")
    print("-" * 80)
    print(f"Total unknown images tested: {total}")
    print(f"False Positives (FP): {fp_count} ({fp_count / total * 100:.1f}%)")
    print(f"True Negatives (TN): {tn_count} ({tn_count / total * 100:.1f}%)")
    print(f"False Positive Rate: {fpr:.4f} ({fpr * 100:.2f}%)")
    print()

    if false_positives:
        print("FALSE POSITIVE DETAILS:")
        for i, fp in enumerate(false_positives, 1):
            score_str = f" (score: {fp['score']:.3f})" if fp.get("score") is not None else ""
            print(f"  {i}. {fp['image']} → incorrectly matched to {fp['matched_to']}{score_str}")
            print(f"     Path: {fp['path']}")
        print()

    # Similarity score statistics (for images with detected faces)
    if all_similarity_scores:
        print("-" * 80)
        print("RECOGNITION SIMILARITY SCORE STATISTICS:")
        print("-" * 80)
        print(f"Samples (with face detected): {len(all_similarity_scores)}/{total}")
        threshold = 1.0 - settings.recognition.tolerance
        print(f"Recognition threshold: {threshold:.3f}")
        print()

        scores_array = np.array(all_similarity_scores)
        print(f"  Maximum:        {np.max(scores_array):.3f}")
        print(f"  90th percentile: {np.percentile(scores_array, 90):.3f}")
        print(f"  75th percentile: {np.percentile(scores_array, 75):.3f}")
        print(f"  Median (50th):   {np.percentile(scores_array, 50):.3f}")
        print(f"  25th percentile: {np.percentile(scores_array, 25):.3f}")
        print(f"  Mean:           {np.mean(scores_array):.3f}")
        print(f"  Std deviation:  {np.std(scores_array):.3f}")
        print()

        # Show safety margin (distance from threshold)
        max_score = np.max(scores_array)
        safety_margin = threshold - max_score
        print(f"Safety margin (threshold - max score): {safety_margin:.3f}")
        if safety_margin > 0.1:
            print("  ✅ Excellent safety margin (>0.1)")
        elif safety_margin > 0.05:
            print("  ✓ Good safety margin (>0.05)")
        elif safety_margin > 0.0:
            print("  ⚠️  Small safety margin (<0.05) - consider lowering tolerance")
        else:
            print("  ❌ CRITICAL: Max score exceeds threshold - review false positives!")
        print()

    return {
        "total": total,
        "false_positives": fp_count,
        "true_negatives": tn_count,
        "fpr": fpr,
        "false_positive_details": false_positives,
    }


def analyze_missed_detections(
    settings: Settings,
    db,
    det_thresh_known: float | None = None,
    det_thresh_test: float | None = None,
    return_best_known: bool = True,
    return_best_test: bool = True,
    output_dir: Path | None = None,
) -> dict[str, list[np.ndarray]]:
    """
    Run LOOCV and identify all missed detections using production settings.

    Args:
        settings: Production Settings instance from config.yaml
        db: Database instance for caching embeddings
        det_thresh_known: Override detection threshold for known_people images (default: from config)
        det_thresh_test: Override detection threshold for test images (default: from config)
        return_best_known: Use only highest confidence face in support images (default: True = production)
        return_best_test: Use only highest confidence face in test images (default: True = production)
        output_dir: Optional directory to save visualization images (detection and recognition)

    Returns:
        Dictionary of known people encodings (for Phase 3 FPR testing)
    """
    # Declare globals for backend-specific functions
    global _get_app, _cosine_sim

    # Use config values unless overridden
    det_thresh_known = det_thresh_known or settings.recognition.det_thresh_known
    det_thresh_test = det_thresh_test or settings.recognition.det_thresh

    print("=" * 80)
    print("MISSED DETECTION ANALYSIS (PRODUCTION SETTINGS)")
    print("=" * 80)
    print(f"Config file: {settings}")
    print(f"Backend: {settings.recognition.backend}")
    print(
        f"Augmentation: {'Enabled' if settings.recognition.backend in ('insightface', 'auraface') else 'N/A'}"
    )
    print(f"Tolerance: {settings.recognition.tolerance}")
    print(f"Min face size: {settings.recognition.min_face_size_pixels}px")
    print(f"Detection threshold (known faces): {det_thresh_known}")
    print(f"Detection threshold (test images): {det_thresh_test}")
    print(f"Return best only (known): {return_best_known}")
    print(f"Return best only (test): {return_best_test}")
    print(f"Cache: {'Enabled' if db else 'Disabled'}")
    print("=" * 80)
    print()

    # Collect all failures
    failures = []
    total_tests = 0
    person_stats = {}

    known_people_path = settings.known_people_dir

    print("Phase 1: Loading all embeddings from full directory (PRODUCTION FLOW)...")
    print("-" * 80)

    # PRODUCTION-MATCHING OPTIMIZATION: Load entire known_people directory ONCE with per-file metadata
    # This creates a SINGLE cache entry (just like production), then we filter per LOOCV iteration
    # Benefits: Matches production exactly, 100x faster with cache, proper validation
    all_person_embeddings_with_paths, _ = factory.load_known_faces(
        str(known_people_path),
        backend_name=settings.recognition.backend,
        min_face_size=settings.recognition.min_face_size_pixels,
        enable_augmentation=True,
        det_thresh_known=det_thresh_known,
        return_best_only=return_best_known,
        return_per_file=True,  # Get per-file metadata for LOOCV filtering
        db=db,  # Uses same cache as production
    )

    print(f"✓ Loaded embeddings for {len(all_person_embeddings_with_paths)} people")

    # Visualize detections in known_people images if output directory specified
    if output_dir and settings.recognition.backend in ("insightface", "auraface"):
        detection_dir = output_dir / "1_detection"
        detection_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nVisualizing detections (saved to {detection_dir})...")

        # Import backend-specific functions
        if settings.recognition.backend == "insightface":
            from dmaf.face_recognition.insightface_backend import _get_app
        else:  # auraface
            from dmaf.face_recognition.auraface_backend import _get_app

        app = _get_app(det_thresh=det_thresh_known)
        for person_name, file_list in all_person_embeddings_with_paths.items():
            for filename, _ in file_list:
                img_path = known_people_path / person_name / filename
                img_np = np.array(Image.open(img_path).convert("RGB"))
                faces = app.get(img_np)

                # Filter by min_face_size and collect with confidence scores
                min_face = settings.recognition.min_face_size_pixels
                valid_faces_with_scores = []
                for f in faces:
                    x1, y1, x2, y2 = map(int, f.bbox)
                    if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
                        valid_faces_with_scores.append((f.det_score, f))

                # Determine which face was chosen (highest confidence if return_best_only)
                chosen_face_idx = None
                if valid_faces_with_scores:
                    # Sort by confidence (descending)
                    valid_faces_with_scores.sort(key=lambda x: x[0], reverse=True)
                    valid_faces = [f for _, f in valid_faces_with_scores]

                    # If return_best_only and multiple faces, index 0 is chosen
                    if return_best_known and len(valid_faces) > 1:
                        chosen_face_idx = 0
                else:
                    valid_faces = []

                output_path = detection_dir / person_name / filename
                visualize_detections(
                    img_path,
                    output_path,
                    valid_faces,
                    chosen_face_idx,
                    title=f"{person_name}/{filename}",
                )

    # Convert Path objects to filenames and build full path mapping
    all_person_embeddings = {}
    for person_name, file_list in all_person_embeddings_with_paths.items():
        images = sorted(
            list((known_people_path / person_name).glob("*.jpg"))
            + list((known_people_path / person_name).glob("*.png"))
        )

        if len(images) < 2:
            continue

        person_stats[person_name] = {"total": len(images), "failures": [], "matches": []}

        # Build mapping: filename -> (full_path, embeddings)
        filename_to_embeddings = {filename: embeddings for filename, embeddings in file_list}

        # Create list of (full_path, embeddings) for LOOCV
        all_person_embeddings[person_name] = []
        for img_path in images:
            if img_path.name in filename_to_embeddings:
                all_person_embeddings[person_name].append(
                    (img_path, filename_to_embeddings[img_path.name])
                )

    print()
    print("Phase 2: Running LOOCV with pre-computed embeddings...")
    print("-" * 80)

    # Now run LOOCV using pre-computed embeddings
    for person_idx, person_name in enumerate(sorted(all_person_embeddings.keys()), 1):
        img_embeddings_list = all_person_embeddings[person_name]
        total_imgs = len(img_embeddings_list)

        print(
            f"Person {person_idx}/{len(all_person_embeddings)}: {person_name} ({total_imgs} images)"
        )

        # LOOCV: For each image, train on N-1, test on 1
        for test_idx, (test_img_path, _) in enumerate(img_embeddings_list):
            total_tests += 1

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
                backend_name=settings.recognition.backend,
                tolerance=settings.recognition.tolerance,
                min_face_size=settings.recognition.min_face_size_pixels,
                det_thresh=det_thresh_test,
                return_best_only=return_best_test,
            )

            # Visualize recognition if output directory specified
            if output_dir and settings.recognition.backend in ("insightface", "auraface"):
                recognition_dir = output_dir / "2_recognition" / person_name
                recognition_dir.mkdir(parents=True, exist_ok=True)

                # Import backend-specific functions if not already imported
                if _get_app is None:
                    if settings.recognition.backend == "insightface":
                        from dmaf.face_recognition.insightface_backend import _get_app
                    else:  # auraface
                        from dmaf.face_recognition.auraface_backend import _get_app

                # Run detection to get face objects for visualization
                app = _get_app(det_thresh=det_thresh_test)
                faces = app.get(test_img_np)

                # Filter by min_face_size and collect embeddings per face
                min_face = settings.recognition.min_face_size_pixels
                valid_faces = []
                per_face_embeddings = []  # List of embeddings, one per face
                for f in faces:
                    x1, y1, x2, y2 = map(int, f.bbox)
                    if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
                        valid_faces.append(f)
                        per_face_embeddings.append([f.normed_embedding.astype(np.float32)])

                # Compute similarity scores per face (not combined)
                per_face_match_scores = None
                if per_face_embeddings:
                    per_face_match_scores = [
                        compute_all_similarities(face_embs, encodings)
                        for face_embs in per_face_embeddings
                    ]

                output_path = recognition_dir / test_img_path.name
                visualize_recognition(
                    test_img_path,
                    output_path,
                    valid_faces,
                    per_face_match_scores,
                    who,
                    settings.recognition.tolerance,
                )

            # Check result
            if matched and person_name in who:
                person_stats[person_name]["matches"].append(test_img_path.name)
                print(f"  ✓ {test_img_path.name}")
            elif who == []:
                # who == [] can mean: (1) no face detected, OR (2) face detected but no match
                # We need to distinguish these by checking if faces were actually detected
                face_detected = False
                max_score = 0.0
                max_score_person = None

                if settings.recognition.backend in ("insightface", "auraface"):
                    # Import backend-specific functions if not already imported
                    if _get_app is None:
                        if settings.recognition.backend == "insightface":
                            from dmaf.face_recognition.insightface_backend import (
                                _cosine_sim,
                                _get_app,
                            )
                        else:  # auraface
                            from dmaf.face_recognition.auraface_backend import _cosine_sim, _get_app

                    app = _get_app(det_thresh=det_thresh_test)
                    faces = app.get(test_img_np)

                    if faces:
                        min_face = settings.recognition.min_face_size_pixels
                        for f in faces:
                            x1, y1, x2, y2 = map(int, f.bbox)
                            if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
                                face_detected = True
                                face_embeddings = [f.normed_embedding.astype(np.float32)]
                                similarities = compute_all_similarities(face_embeddings, encodings)

                                for p_name, score in similarities.items():
                                    if score > max_score:
                                        max_score = score
                                        max_score_person = p_name
                                break  # Only check first valid face

                if face_detected:
                    # FACE DETECTED BUT NO RECOGNITION (below threshold)
                    threshold = 1.0 - settings.recognition.tolerance
                    closest_info = (
                        f" (closest: {max_score_person} {max_score:.3f}, threshold: {threshold:.3f})"
                        if max_score_person
                        else ""
                    )

                    person_stats[person_name]["failures"].append(test_img_path.name)
                    failures.append(
                        {
                            "person": person_name,
                            "image": test_img_path.name,
                            "path": str(test_img_path),
                            "reason": f"Face detected but no match (below threshold){closest_info}",
                        }
                    )
                    print(f"  ✗ {test_img_path.name} - FACE DETECTED BUT NO MATCH{closest_info}")
                else:
                    # NO FACE DETECTED
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
                # Matched wrong person (rare) - also show similarity scores
                if settings.recognition.backend in ("insightface", "auraface"):
                    # Import backend-specific functions if not already imported
                    if _get_app is None:
                        if settings.recognition.backend == "insightface":
                            from dmaf.face_recognition.insightface_backend import (
                                _cosine_sim,
                                _get_app,
                            )
                        else:  # auraface
                            from dmaf.face_recognition.auraface_backend import _cosine_sim, _get_app

                    app = _get_app(det_thresh=det_thresh_test)
                    faces = app.get(test_img_np)

                    max_score = 0.0
                    max_score_person = None

                    if faces:
                        min_face = settings.recognition.min_face_size_pixels
                        for f in faces:
                            x1, y1, x2, y2 = map(int, f.bbox)
                            if (x2 - x1) >= min_face and (y2 - y1) >= min_face:
                                face_embeddings = [f.normed_embedding.astype(np.float32)]
                                similarities = compute_all_similarities(face_embeddings, encodings)

                                for p_name, score in similarities.items():
                                    if score > max_score:
                                        max_score = score
                                        max_score_person = p_name
                                break

                    threshold = 1.0 - settings.recognition.tolerance
                    closest_info = (
                        f" (matched: {max_score_person} {max_score:.3f}, expected: {person_name}, threshold: {threshold:.3f})"
                        if max_score_person
                        else ""
                    )
                else:
                    closest_info = f" (matched: {who}, expected: {person_name})"

                person_stats[person_name]["failures"].append(test_img_path.name)
                failures.append(
                    {
                        "person": person_name,
                        "image": test_img_path.name,
                        "path": str(test_img_path),
                        "reason": f"Matched wrong person{closest_info}",
                    }
                )
                print(f"  ✗ {test_img_path.name} - WRONG MATCH{closest_info}")

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
        print("1. Lower detection thresholds:")
        print("   python scripts/debug_missed_detections.py --det-thresh-known 0.3")
        print()
        print("2. Test detection parameters (InsightFace/AuraFace):")
        print("   # For InsightFace:")
        print("   from dmaf.face_recognition.insightface_backend import _get_app")
        print("   # For AuraFace:")
        print("   # from dmaf.face_recognition.auraface_backend import _get_app")
        print("   from PIL import Image")
        print("   import numpy as np")
        print()
        print("   app = _get_app(det_thresh=0.35)")
        print("   img = Image.open('/path/to/failed/image.jpg').convert('RGB')")
        print("   img_np = np.array(img)")
        print("   faces = app.get(img_np)")
        print("   print(f'Detected {len(faces)} faces')")
        print()
        print("3. Adjust config.yaml:")
        print("   recognition:")
        print("     det_thresh: 0.35  # Lower = more faces detected")
        print("     min_face_size_pixels: 60  # Allow smaller faces")
        print()

    else:
        print("🎉 NO FAILURES! All images detected successfully.")

    # Build full encodings dictionary for Phase 3 (FPR testing)
    # This contains ALL embeddings from ALL known people (no LOOCV filtering)
    full_encodings = {}
    for person_name, file_list in all_person_embeddings_with_paths.items():
        full_encodings[person_name] = []
        for filename, embeddings in file_list:
            full_encodings[person_name].extend(embeddings)

    return full_encodings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Debug missed face detections using production settings"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("config.yaml"),
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--det-thresh-known",
        type=float,
        default=None,
        help="Override detection threshold for known faces (default: from config)",
    )
    parser.add_argument(
        "--det-thresh-test",
        type=float,
        default=None,
        help="Override detection threshold for test images (default: from config)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable embedding cache (slower but ensures fresh computation)",
    )
    parser.add_argument(
        "--clear-cache",
        default=True,
        action="store_true",
        help="Clear embedding cache before running (ensures fresh results with current parameters)",
    )
    parser.add_argument(
        "--return-best-known",
        action="store_true",
        help="Use only highest confidence face in support images (default: True = production)",
    )
    parser.add_argument(
        "--return-best-test",
        action="store_true",
        help="Use only highest confidence face in test images (default: True = production)",
    )
    parser.add_argument(
        "--use-all-faces-known",
        action="store_true",
        help="Use ALL detected faces in support images (overrides return_best_known to False)",
    )
    parser.add_argument(
        "--use-all-faces-test",
        action="store_true",
        help="Use ALL detected faces in test images (overrides return_best_test to False)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        help="Directory to save visualization images (detection and recognition phases)",
    )
    parser.add_argument(
        "--unknown-people-dir",
        "-u",
        type=Path,
        default=Path("data/unknown_people"),
        help="Directory containing images of unknown people for FPR testing (default: data/unknown_people)",
    )
    args = parser.parse_args()

    # Load production settings
    try:
        settings = Settings.from_yaml(args.config)
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {args.config}", file=sys.stderr)
        print("Create a config.yaml file based on config.example.yaml", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: Invalid configuration: {e}", file=sys.stderr)
        sys.exit(1)

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Suppress verbose InsightFace model loading messages
    logging.getLogger("insightface").setLevel(logging.WARNING)

    # Create database connection for caching (unless --no-cache)
    db = None
    if not args.no_cache:
        if settings.dedup.backend == "sqlite":
            db = get_database("sqlite", db_path=str(settings.dedup.db_path))
            logger.info(f"Using SQLite database for caching: {settings.dedup.db_path}")

            # Clear embedding cache if requested (keeps dedup data intact)
            if args.clear_cache:
                import sqlite3

                conn = sqlite3.connect(str(settings.dedup.db_path))
                cursor = conn.cursor()
                cursor.execute("DELETE FROM embedding_cache")
                deleted = cursor.rowcount
                conn.commit()
                conn.close()
                logger.info(f"Cleared {deleted} cached embedding entries")
        elif settings.dedup.backend == "firestore":
            db = get_database(
                "firestore",
                project_id=settings.dedup.firestore_project,
                collection=settings.dedup.firestore_collection,
            )
            logger.info(f"Using Firestore for caching: project={settings.dedup.firestore_project}")

            if args.clear_cache:
                logger.warning("--clear-cache not implemented for Firestore backend")

    # Determine return_best_only values (default: True, can override with --use-all-faces-*)
    return_best_known = (
        not args.use_all_faces_known if hasattr(args, "use_all_faces_known") else True
    )
    return_best_test = not args.use_all_faces_test if hasattr(args, "use_all_faces_test") else True

    # Run Phase 1-2: LOOCV analysis
    det_thresh_test = args.det_thresh_test or settings.recognition.det_thresh
    full_encodings = analyze_missed_detections(
        settings=settings,
        db=db,
        det_thresh_known=args.det_thresh_known,
        det_thresh_test=args.det_thresh_test,
        return_best_known=return_best_known,  # Production default: True (use best face)
        return_best_test=return_best_test,  # Production default: True (match best face)
        output_dir=args.output_dir,  # Optional visualization output directory
    )

    # Run Phase 3: False Positive Rate testing (if unknown_people directory exists)
    if full_encodings:
        test_unknown_people(
            settings=settings,
            unknown_people_dir=args.unknown_people_dir,
            encodings=full_encodings,
            det_thresh_test=det_thresh_test,
            return_best_test=return_best_test,
            output_dir=args.output_dir,
        )

    print("=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
