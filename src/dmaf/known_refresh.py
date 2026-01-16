"""
Known people auto-refresh functionality.

Periodically adds cropped face images from matched uploads to the known_people
directory to improve recognition accuracy as people's appearances change over time.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from dmaf.config import KnownRefreshSettings
from dmaf.database import Database

# Import face detection function (optional dependency)
try:
    from dmaf.face_recognition.insightface_backend import get_face_bbox
except ImportError:
    get_face_bbox = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class RefreshCandidate:
    """Candidate image for refresh."""

    person_name: str
    source_path: str
    match_score: float
    score_delta: float  # abs(score - target_score)


@dataclass
class RefreshResult:
    """Result of a refresh operation."""

    person_name: str
    source_file_path: str
    target_file_path: str
    match_score: float
    target_score: float


class KnownRefreshManager:
    """Manages automatic refresh of known_people images."""

    def __init__(
        self,
        config: KnownRefreshSettings,
        db: Database,
        known_people_dir: Path,
        backend_name: str,
    ):
        """
        Initialize refresh manager.

        Args:
            config: Refresh configuration settings
            db: Database connection
            known_people_dir: Path to known_people directory
            backend_name: Face recognition backend ('insightface' or 'face_recognition')
        """
        self.config = config
        self.db = db
        self.known_people_dir = Path(known_people_dir)
        self.backend_name = backend_name

    def should_refresh(self) -> bool:
        """
        Check if refresh should be performed.

        Returns:
            True if refresh is due, False otherwise
        """
        if not self.config.enabled:
            return False

        last_refresh = self.db.get_last_refresh_time()

        if last_refresh is None:
            # No refresh has ever been performed
            logger.info("No previous refresh found - refresh is due")
            return True

        # Check if enough time has passed
        now = datetime.now()
        time_since_last = now - last_refresh
        interval = timedelta(days=self.config.interval_days)

        if time_since_last >= interval:
            logger.info(
                f"Last refresh was {time_since_last.days} days ago, "
                f"interval is {self.config.interval_days} days - refresh is due"
            )
            return True

        logger.debug(
            f"Last refresh was {time_since_last.days} days ago, "
            f"next refresh in {(interval - time_since_last).days} days"
        )
        return False

    def find_candidates(self, person_name: str) -> list[RefreshCandidate]:
        """
        Find candidate images for refresh for a given person.

        Selects uploaded images with scores closest to target_score.

        Args:
            person_name: Name of person to find candidates for

        Returns:
            List of refresh candidates, sorted by score_delta ascending
        """
        candidates = self.db.get_refresh_candidates(person_name, self.config.target_score)

        return [
            RefreshCandidate(
                person_name=person_name,
                source_path=c["path"],
                match_score=c["match_score"],
                score_delta=c["score_delta"],
            )
            for c in candidates
        ]

    def crop_face(self, image_path: str, padding_percent: float = 0.3) -> Image.Image | None:
        """
        Crop face from an image with padding.

        Args:
            image_path: Path to source image
            padding_percent: Padding around face bbox as percentage (0.3 = 30%)

        Returns:
            Cropped PIL Image, or None if face detection fails
        """
        try:
            # Load image
            img_pil = Image.open(image_path).convert("RGB")
            img_rgb = np.array(img_pil)

            # Get face bounding box
            if self.backend_name == "insightface":
                if get_face_bbox is None:
                    logger.error("insightface backend not available")
                    return None
                bbox = get_face_bbox(img_rgb)
            else:
                # dlib backend doesn't have get_face_bbox yet
                logger.warning(
                    f"Face bbox extraction not supported for {self.backend_name} backend"
                )
                return None

            if bbox is None:
                logger.warning(f"No face detected in {image_path}")
                return None

            x1, y1, x2, y2 = bbox
            width = x2 - x1
            height = y2 - y1

            # Add padding
            pad_w = int(width * padding_percent)
            pad_h = int(height * padding_percent)

            x1_padded = max(0, x1 - pad_w)
            y1_padded = max(0, y1 - pad_h)
            x2_padded = min(img_pil.width, x2 + pad_w)
            y2_padded = min(img_pil.height, y2 + pad_h)

            # Crop
            cropped = img_pil.crop((x1_padded, y1_padded, x2_padded, y2_padded))

            logger.debug(
                f"Cropped face from {image_path}: "
                f"bbox=({x1},{y1},{x2},{y2}) -> "
                f"cropped=({x1_padded},{y1_padded},{x2_padded},{y2_padded})"
            )

            return cropped

        except Exception as e:
            logger.error(f"Failed to crop face from {image_path}: {e}")
            return None

    def run_refresh(self) -> list[RefreshResult]:
        """
        Run the refresh operation for all known people.

        For each person, finds the best candidate image (closest to target_score),
        crops the face, and saves it to known_people directory.

        Returns:
            List of refresh results
        """
        if not self.should_refresh():
            logger.info("Refresh not due, skipping")
            return []

        logger.info("Starting known_people refresh")

        results = []

        # Get list of known people from directory structure
        if not self.known_people_dir.exists():
            logger.error(f"Known people directory not found: {self.known_people_dir}")
            return []

        for person_dir in self.known_people_dir.iterdir():
            if not person_dir.is_dir():
                continue

            person_name = person_dir.name

            # Find best candidate
            candidates = self.find_candidates(person_name)

            if not candidates:
                logger.info(f"No refresh candidates found for {person_name}")
                continue

            # Select best candidate (closest to target score)
            best_candidate = candidates[0]

            logger.info(
                f"Selected refresh candidate for {person_name}: "
                f"{best_candidate.source_path} (score: {best_candidate.match_score:.2f}, "
                f"delta: {best_candidate.score_delta:.3f})"
            )

            # Crop face
            cropped_img = self.crop_face(
                best_candidate.source_path, self.config.crop_padding_percent
            )

            if cropped_img is None:
                logger.warning(f"Failed to crop face for {person_name}, skipping")
                continue

            # Generate target filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_filename = f"refresh_{timestamp}_{best_candidate.match_score:.2f}.jpg"
            target_path = person_dir / target_filename

            # Save cropped image
            try:
                cropped_img.save(target_path, format="JPEG", quality=95)
                logger.info(f"Saved refresh image to {target_path}")
            except Exception as e:
                logger.error(f"Failed to save refresh image to {target_path}: {e}")
                continue

            # Record in database
            self.db.add_refresh_record(
                person_name,
                best_candidate.source_path,
                str(target_path),
                best_candidate.match_score,
                self.config.target_score,
            )

            results.append(
                RefreshResult(
                    person_name=person_name,
                    source_file_path=best_candidate.source_path,
                    target_file_path=str(target_path),
                    match_score=best_candidate.match_score,
                    target_score=self.config.target_score,
                )
            )

        logger.info(f"Refresh complete: added {len(results)} image(s)")
        return results
