# main entry point
import io
import yaml
import logging
from pathlib import Path
from PIL import Image
from db import get_conn
from face_index import load_known_faces, best_match
from photos_api import get_creds, ensure_album, upload_bytes, create_media_item
from watcher import NewImageHandler, run_watch

def build_processor(known_root, backend, tolerance, min_face_size):
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
    encodings, _ = load_known_faces(known_root, backend_name=backend, min_face_size=min_face_size)

    def process(np_img):
        return best_match(
            encodings,
            np_img,
            backend_name=backend,
            tolerance=tolerance,
            min_face_size=min_face_size
        )
    return process

def main():
    cfg = yaml.safe_load(open("config.yaml"))
    logging.basicConfig(level=getattr(logging, cfg.get("log_level","INFO")))
    conn = get_conn(cfg["dedup"]["db_path"])

    # Get backend from config (default to face_recognition for backwards compatibility)
    backend = cfg.get("recognition", {}).get("backend", "face_recognition")
    logging.info(f"Using face recognition backend: {backend}")

    process_fn = build_processor(
        cfg["known_people_dir"],
        backend,
        cfg["recognition"]["tolerance"],
        cfg["recognition"]["min_face_size_pixels"]
    )

    creds = get_creds()
    album_id = None
    album_name = cfg.get("google_photos_album_name")
    if album_name:
        try:
            album_id = ensure_album(creds, album_name)
        except Exception as e:
            logging.warning(f"Album ensure failed - continuing without album: {e}")
            album_id = None

    class Uploader(NewImageHandler):
        def on_match(self, p: Path, who):
            # Convert to JPEG bytes for broad compatibility
            img = Image.open(p).convert("RGB")
            bio = io.BytesIO()
            img.save(bio, format="JPEG", quality=92)
            up_token = upload_bytes(creds, bio.getvalue(), p.name)
            _id = create_media_item(creds, up_token, album_id, description=f"Auto-import: {', '.join(who)}")
            self.db_conn.mark_uploaded(str(p))
            logging.info(f"Uploaded -> MediaItem { _id }")

    handler = Uploader(process_fn, conn, cfg)
    run_watch(cfg["watch_dirs"], handler)

if __name__ == "__main__":
    main()
