# watcher logic
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


@dataclass
class ScanResult:
    """Result of a batch scan operation."""

    new_files: int
    processed: int
    matched: int
    uploaded: int
    errors: int
    success: bool


def sha256_of_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class NewImageHandler(FileSystemEventHandler):
    def __init__(self, process_fn, db_conn, cfg, alert_manager=None):
        super().__init__()
        self.process_fn = process_fn
        self.db_conn = db_conn
        self.cfg = cfg
        self.alert_manager = alert_manager
        self.logger = logging.getLogger(__name__)

    def on_created(self, event):
        if event.is_directory:
            return
        p = Path(event.src_path)
        if p.suffix.lower() not in [".jpg", ".jpeg", ".png", ".heic", ".webp"]:
            return
        # WhatsApp sometimes writes then finalizes - wait briefly
        time.sleep(0.8)
        try:
            self._handle_file(p)
        except Exception as e:
            logging.exception(f"Error processing {p}: {e}")

    def _handle_file(self, p: Path):
        if self.db_conn.seen(str(p)):
            return
        try:
            img = Image.open(p).convert("RGB")
        except Exception as e:
            # Record error if alert_manager available
            if self.alert_manager:
                self.alert_manager.record_error("processing", str(e), str(p))
            return

        np_img = np.array(img)
        h = sha256_of_file(p)

        # Call process_fn - it now returns scores if configured
        result = self.process_fn(np_img)

        # Handle both old (matched, who) and new (matched, who, scores) formats
        if len(result) == 3:
            matched, who, scores = result
        else:
            matched, who = result
            scores = {}

        # Extract best score and person
        best_score = max(scores.values()) if scores else None
        best_person = max(scores, key=scores.get) if scores else None

        # Check for borderline events (close to but below threshold)
        if self.alert_manager and best_score is not None and not matched:
            tolerance = self.cfg.recognition.tolerance
            borderline_offset = self.cfg.alerting.borderline_offset
            threshold = 1.0 - tolerance
            borderline_low = threshold - borderline_offset

            if borderline_low <= best_score < threshold:
                self.alert_manager.record_borderline(str(p), best_score, tolerance, best_person)

        # Store with scores
        self.db_conn.add_file_with_score(
            str(p), h, int(matched), 0, best_score, best_person if matched else None
        )

        if matched:
            self.logger.info(f"Match {p.name} -> {who}")
            self.on_match(p, who)
            # Delete source if configured (after successful upload)
            if self.cfg.delete_source_after_upload:
                try:
                    p.unlink()
                    self.logger.info(f"Deleted source: {p.name}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete {p.name}: {e}")
        else:
            self.logger.info(f"No match {p.name}")
            # Delete unmatched if configured (staging cleanup)
            if self.cfg.delete_unmatched_after_processing:
                try:
                    p.unlink()
                    self.logger.info(f"Deleted unmatched: {p.name}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete unmatched {p.name}: {e}")

    def on_match(self, p: Path, who):
        pass  # overridden by caller


def run_watch(dirs, handler):
    obs = Observer()
    for d in dirs:
        pd = Path(d)
        pd.mkdir(parents=True, exist_ok=True)
        obs.schedule(handler, str(pd), recursive=False)
    obs.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()


def scan_and_process_once(dirs, handler) -> ScanResult:
    """
    Scan all directories once, process new images, then exit.

    Used for batch/scheduled execution instead of continuous watching.
    Processes all image files in the directories that haven't been seen before.

    Args:
        dirs: List of directory paths to scan
        handler: NewImageHandler instance with process_fn and db_conn

    Returns:
        ScanResult with statistics about the scan operation
    """
    logger = logging.getLogger(__name__)

    new_files = 0
    processed = 0
    matched = 0
    errors = 0

    image_extensions = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

    for dir_path in dirs:
        pd = Path(dir_path)
        if not pd.exists():
            logger.warning(f"Directory does not exist: {pd}")
            continue

        logger.info(f"Scanning directory: {pd}")

        # Find all image files in directory
        for image_path in pd.iterdir():
            if not image_path.is_file():
                continue
            if image_path.suffix.lower() not in image_extensions:
                continue

            # Check if already processed
            if handler.db_conn.seen(str(image_path)):
                continue

            new_files += 1

            try:
                # Process the image (same logic as _handle_file)
                img = Image.open(image_path).convert("RGB")
                np_img = np.array(img)
                h = sha256_of_file(image_path)

                # Call process_fn - it now returns scores if configured
                result = handler.process_fn(np_img)

                # Handle both old (matched, who) and new (matched, who, scores) formats
                if len(result) == 3:
                    is_matched, who, scores = result
                else:
                    is_matched, who = result
                    scores = {}

                # Extract best score and person
                best_score = max(scores.values()) if scores else None
                best_person = max(scores, key=scores.get) if scores else None

                # Check for borderline events (close to but below threshold)
                if handler.alert_manager and best_score is not None and not is_matched:
                    tolerance = handler.cfg.recognition.tolerance
                    borderline_offset = handler.cfg.alerting.borderline_offset
                    threshold = 1.0 - tolerance
                    borderline_low = threshold - borderline_offset

                    if borderline_low <= best_score < threshold:
                        handler.alert_manager.record_borderline(
                            str(image_path), best_score, tolerance, best_person
                        )

                # Store with scores
                handler.db_conn.add_file_with_score(
                    str(image_path),
                    h,
                    int(is_matched),
                    0,
                    best_score,
                    best_person if is_matched else None,
                )
                processed += 1

                if is_matched:
                    matched += 1
                    logger.info(f"Match {image_path.name} -> {who}")

                    # Call on_match hook for uploading
                    try:
                        handler.on_match(image_path, who)
                        # Delete source if configured (after successful upload)
                        if handler.cfg.delete_source_after_upload:
                            try:
                                image_path.unlink()
                                logger.info(f"Deleted source: {image_path.name}")
                            except Exception as e:
                                logger.warning(f"Failed to delete {image_path.name}: {e}")
                    except Exception as e:
                        logger.error(f"Upload failed for {image_path.name}: {e}")
                        errors += 1
                        # Record error if alert_manager available
                        if handler.alert_manager:
                            handler.alert_manager.record_error("upload", str(e), str(image_path))
                else:
                    logger.info(f"No match {image_path.name}")
                    # Delete unmatched if configured (staging cleanup)
                    if handler.cfg.delete_unmatched_after_processing:
                        try:
                            image_path.unlink()
                            logger.info(f"Deleted unmatched: {image_path.name}")
                        except Exception as e:
                            logger.warning(f"Failed to delete unmatched {image_path.name}: {e}")

            except Exception as e:
                logger.error(f"Error processing {image_path.name}: {e}")
                errors += 1
                # Record error if alert_manager available
                if handler.alert_manager:
                    handler.alert_manager.record_error("processing", str(e), str(image_path))

    success = errors == 0 and processed == new_files

    logger.info(
        f"Scan complete: {new_files} new files, "
        f"{processed} processed, {matched} matched, {errors} errors"
    )

    return ScanResult(
        new_files=new_files,
        processed=processed,
        matched=matched,
        uploaded=matched - errors,  # Successful uploads
        errors=errors,
        success=success,
    )
