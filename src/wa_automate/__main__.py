"""
Entry point for running wa_automate as a module.

Usage:
    python -m wa_automate
    python -m wa_automate --config /path/to/config.yaml
"""

import argparse
import io
import logging
import sys
from pathlib import Path

from PIL import Image

from wa_automate.config import Settings
from wa_automate.database import get_conn
from wa_automate.face_recognition import best_match, load_known_faces
from wa_automate.google_photos import create_media_item, ensure_album, get_creds, upload_bytes
from wa_automate.watcher import NewImageHandler, run_watch


def build_processor(known_root: Path, backend: str, tolerance: float, min_face_size: int):
    """
    Build a face recognition processor function.

    Args:
        known_root: Path to directory containing known people images
        backend: Face recognition backend ('face_recognition' or 'insightface')
        tolerance: Matching threshold
        min_face_size: Minimum face size in pixels

    Returns:
        Function that takes an image and returns (matched, person_names)
    """
    encodings, _ = load_known_faces(
        str(known_root), backend_name=backend, min_face_size=min_face_size
    )

    def process(np_img):
        return best_match(
            encodings,
            np_img,
            backend_name=backend,
            tolerance=tolerance,
            min_face_size=min_face_size,
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

    conn = get_conn(str(settings.dedup.db_path))

    logger.info(f"Using face recognition backend: {settings.recognition.backend}")

    process_fn = build_processor(
        settings.known_people_dir,
        settings.recognition.backend,
        settings.recognition.tolerance,
        settings.recognition.min_face_size_pixels,
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
        def on_match(self, p: Path, who: list[str]) -> None:
            img = Image.open(p).convert("RGB")
            bio = io.BytesIO()
            img.save(bio, format="JPEG", quality=92)
            up_token = upload_bytes(creds, bio.getvalue(), p.name)
            _id = create_media_item(
                creds, up_token, album_id, description=f"Auto-import: {', '.join(who)}"
            )
            self.db_conn.mark_uploaded(str(p))
            logger.info(f"Uploaded -> MediaItem {_id}")

    handler = Uploader(process_fn, conn, settings)
    run_watch([str(d) for d in settings.watch_dirs], handler)

    return 0


if __name__ == "__main__":
    sys.exit(main())
