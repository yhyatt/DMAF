# watcher logic
import hashlib
import logging
import time
from pathlib import Path

import numpy as np
from PIL import Image
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


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
