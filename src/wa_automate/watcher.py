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
    def __init__(self, process_fn, db_conn, cfg):
        super().__init__()
        self.process_fn = process_fn
        self.db_conn = db_conn
        self.cfg = cfg

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
        except Exception:
            # Could be still writing or a non-image - skip
            return
        np_img = np.array(img)
        h = sha256_of_file(p)
        matched, who = self.process_fn(np_img)
        self.db_conn.add_file(str(p), h, int(matched), 0)
        if matched:
            logging.info(f"Match {p.name} -> {who}")
            self.on_match(p, who)
        else:
            logging.info(f"No match {p.name}")

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
    uploaded_before = 0
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

                is_matched, who = handler.process_fn(np_img)

                handler.db_conn.add_file(str(image_path), h, int(is_matched), 0)
                processed += 1

                if is_matched:
                    matched += 1
                    logger.info(f"Match {image_path.name} -> {who}")

                    # Call on_match hook for uploading
                    try:
                        handler.on_match(image_path, who)
                    except Exception as e:
                        logger.error(f"Upload failed for {image_path.name}: {e}")
                        errors += 1
                else:
                    logger.info(f"No match {image_path.name}")

            except Exception as e:
                logger.error(f"Error processing {image_path.name}: {e}")
                errors += 1

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
