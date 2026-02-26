"""
Entry point for running dmaf as a module.

Usage:
    python -m dmaf
    python -m dmaf --config /path/to/config.yaml
"""

import argparse
import io
import logging
import sys
from pathlib import Path

from PIL import Image

from dmaf.alerting import AlertManager
from dmaf.config import Settings
from dmaf.database import get_database
from dmaf.face_recognition import best_match, load_known_faces
from dmaf.google_photos import create_media_item, ensure_album, get_creds, upload_bytes
from dmaf.known_refresh import KnownRefreshManager
from dmaf.watcher import NewImageHandler, run_watch, scan_and_process_once


def build_processor(
    known_root: Path,
    backend: str,
    tolerance: float,
    min_face_size: int,
    det_thresh: float = 0.4,
    det_thresh_known: float = 0.3,
    return_best_only: bool = True,
    db=None,
    return_scores: bool = True,
):
    """
    Build a face recognition processor function.

    Args:
        known_root: Path to directory containing known people images
        backend: Face recognition backend ('face_recognition' or 'insightface')
        tolerance: Matching threshold
        min_face_size: Minimum face size in pixels
        det_thresh: Detection confidence threshold for test images (insightface only)
        det_thresh_known: Detection confidence threshold for known_people images (insightface only)
        return_best_only: Use only highest confidence face (handles group photos)
        db: Optional database for caching embeddings (100x faster startup)
        return_scores: If True, return scores with results (for alerting & refresh features)

    Returns:
        Function that takes an image and returns:
        - If return_scores=False: (matched, person_names)
        - If return_scores=True: (matched, person_names, scores_dict)
    """
    encodings, _ = load_known_faces(
        str(known_root),
        backend_name=backend,
        min_face_size=min_face_size,
        det_thresh_known=det_thresh_known,
        return_best_only=return_best_only,
        db=db,
    )

    def process(np_img):
        return best_match(
            encodings,
            np_img,
            backend_name=backend,
            tolerance=tolerance,
            min_face_size=min_face_size,
            det_thresh=det_thresh,
            return_best_only=return_best_only,
            return_scores=return_scores,
        )

    return process


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Automated WhatsApp media backup with face recognition filtering"
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("config.yaml"),
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--scan-once",
        action="store_true",
        help="Scan directories once, process new files, then exit (for batch/cron/cloud use)",
    )
    args = parser.parse_args(argv)

    # Load and validate configuration
    try:
        settings = Settings.from_yaml(args.config)
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {args.config}", file=sys.stderr)
        print("Create a config.yaml file based on config.example.yaml", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: Invalid configuration: {e}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Create database connection with appropriate backend
    if settings.dedup.backend == "sqlite":
        conn = get_database("sqlite", db_path=str(settings.dedup.db_path))
        logger.info(f"Using SQLite database: {settings.dedup.db_path}")
    elif settings.dedup.backend == "firestore":
        conn = get_database(
            "firestore",
            project_id=settings.dedup.firestore_project,
            collection=settings.dedup.firestore_collection,
        )
        logger.info(
            f"Using Firestore: project={settings.dedup.firestore_project}, "
            f"collection={settings.dedup.firestore_collection}"
        )
    else:
        raise ValueError(f"Unknown database backend: {settings.dedup.backend}")

    # Download known_people from GCS if configured
    if settings.known_people_gcs_uri:
        from dmaf.gcs_watcher import download_known_people

        logger.info(f"Downloading known_people from {settings.known_people_gcs_uri}...")
        count = download_known_people(settings.known_people_gcs_uri, settings.known_people_dir)
        logger.info(f"Downloaded {count} reference images")
        if count == 0:
            logger.warning(
                "No reference images were downloaded from GCS. "
                "Face recognition may not function as expected."
            )

    logger.info(f"Using face recognition backend: {settings.recognition.backend}")

    # Initialize alert manager if enabled
    alert_manager = None
    if settings.alerting.enabled:
        alert_manager = AlertManager(settings.alerting, conn)
        logger.info("Alert manager initialized")

    # Run database cleanup if alerting is enabled
    if settings.alerting.enabled:
        deleted = conn.cleanup_old_events(settings.alerting.event_retention_days)
        if sum(deleted) > 0:
            logger.info(
                f"Cleanup: deleted {deleted[0]} borderline + {deleted[1]} error events "
                f"older than {settings.alerting.event_retention_days} days"
            )

    # Check if known refresh is due
    if settings.known_refresh.enabled:
        refresh_mgr = KnownRefreshManager(
            settings.known_refresh,
            conn,
            settings.known_people_dir,
            settings.recognition.backend,
        )

        if refresh_mgr.should_refresh():
            logger.info("Known refresh is due, running refresh operation")
            refresh_results = refresh_mgr.run_refresh()

            if refresh_results and alert_manager:
                # Send immediate notification for refresh
                alert_manager.send_refresh_notification(
                    [
                        {
                            "person_name": r.person_name,
                            "source_file_path": r.source_file_path,
                            "target_file_path": r.target_file_path,
                            "match_score": r.match_score,
                            "target_score": r.target_score,
                        }
                        for r in refresh_results
                    ]
                )

            # Reload known faces after refresh (new images added)
            if refresh_results:
                logger.info("Reloading known faces after refresh")

    # Build processor with embedding cache for fast startup
    process_fn = build_processor(
        settings.known_people_dir,
        settings.recognition.backend,
        settings.recognition.tolerance,
        settings.recognition.min_face_size_pixels,
        settings.recognition.det_thresh,
        settings.recognition.det_thresh_known,
        settings.recognition.return_best_only,
        db=conn,  # Pass database for embedding cache
        return_scores=True,  # Enable score tracking for alerting/refresh
    )

    creds = get_creds()
    album_id = None
    if settings.google_photos_album_name:
        try:
            album_id = ensure_album(creds, settings.google_photos_album_name)
        except Exception as e:
            logger.warning(f"Album ensure failed - continuing without album: {e}")
            album_id = None

    class Uploader(NewImageHandler):
        def on_match_video(self, p: Path, who: list[str], dedup_key: str | None = None) -> None:
            key = dedup_key or str(p)
            max_video_bytes = 200 * 1024 * 1024  # 200 MB — Cloud Run has 2 GB RAM
            # Size guard lives outside try/except so RuntimeError is not re-caught
            # and record_error is not called twice.
            file_size = p.stat().st_size
            if file_size > max_video_bytes:
                msg = (
                    f"Video {p.name} too large to upload safely "
                    f"({file_size / (1024 * 1024):.1f} MB > 200 MB limit)"
                )
                logger.error(msg)
                if self.alert_manager:
                    self.alert_manager.record_error("upload", msg, key)
                raise RuntimeError(msg)
            try:
                video_bytes = p.read_bytes()
                up_token = upload_bytes(creds, video_bytes, p.name)
                _id = create_media_item(
                    creds, up_token, album_id,
                    description=f"Auto-import video: {', '.join(who)}",
                )
                self.db_conn.mark_uploaded(key)
                logger.info(f"Uploaded video -> MediaItem {_id}")
            except Exception as e:
                logger.error(f"Video upload failed for {p.name}: {e}")
                if self.alert_manager:
                    self.alert_manager.record_error("upload", str(e), key)
                raise

        def on_match(self, p: Path, who: list[str], dedup_key: str | None = None) -> None:
            record_key = dedup_key if dedup_key else str(p)
            try:
                img = Image.open(p).convert("RGB")
                bio = io.BytesIO()
                img.save(bio, format="JPEG", quality=92)
                up_token = upload_bytes(creds, bio.getvalue(), p.name)
                _id = create_media_item(
                    creds, up_token, album_id, description=f"Auto-import: {', '.join(who)}"
                )
                self.db_conn.mark_uploaded(record_key)
                logger.info(f"Uploaded -> MediaItem {_id}")
            except Exception as e:
                logger.error(f"Upload failed for {p.name}: {e}")
                if self.alert_manager:
                    self.alert_manager.record_error("upload", str(e), record_key)
                raise  # Re-raise so scan_and_process_once can count it as error

    handler = Uploader(process_fn, conn, settings, alert_manager=alert_manager)

    if args.scan_once:
        # Batch mode: scan once and exit
        logger.info("Running in batch mode (scan-once)")
        result = scan_and_process_once([str(d) for d in settings.watch_dirs], handler)

        logger.info(
            f"Batch scan complete: {result.new_files} new, "
            f"{result.processed} processed, {result.matched} matched, "
            f"{result.uploaded} uploaded, {result.errors} errors"
        )

        # Check if alerts should be sent after batch processing
        if alert_manager and alert_manager.should_send_alert():
            logger.info("Sending pending alerts")
            events_sent = alert_manager.send_pending_alerts()
            logger.info(f"Sent alert with {events_sent} event(s)")

        return 0 if result.success else 1
    else:
        # Watcher mode: continuous monitoring
        logger.info("Running in watcher mode (continuous)")

        # TODO: In watcher mode, periodically check and send alerts
        # This could be done with a separate thread or using watchdog's timer
        # For now, alerts are only sent in batch mode or manually

        run_watch([str(d) for d in settings.watch_dirs], handler)
        return 0


if __name__ == "__main__":
    sys.exit(main())
