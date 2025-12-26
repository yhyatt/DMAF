# database logic
import sqlite3
import threading
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE,
  sha256 TEXT,
  uploaded INTEGER DEFAULT 0,
  matched INTEGER,
  created_ts DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    """
    Thread-safe SQLite database wrapper.

    Uses thread-local connections to ensure each thread has its own connection,
    preventing "SQLite objects created in a thread can only be used in that same thread" errors.

    For write operations, uses a lock to serialize access and prevent conflicts.
    """

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._write_lock = threading.Lock()

        # Initialize schema on first connection
        conn = self._get_conn()
        conn.execute(SCHEMA)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0  # Wait up to 30s if database is locked
            )
        return self._local.conn

    def seen(self, path: str) -> bool:
        """Check if a file path has been processed before."""
        conn = self._get_conn()
        cur = conn.execute("SELECT 1 FROM files WHERE path=?", (path,))
        return cur.fetchone() is not None

    def add_file(self, path: str, sha256: Optional[str], matched: int, uploaded: int):
        """Add a new file record to the database."""
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO files(path, sha256, matched, uploaded) VALUES(?,?,?,?)",
                (path, sha256, matched, uploaded)
            )
            conn.commit()

    def mark_uploaded(self, path: str):
        """Mark a file as uploaded to Google Photos."""
        with self._write_lock:
            conn = self._get_conn()
            conn.execute("UPDATE files SET uploaded=1 WHERE path=?", (path,))
            conn.commit()

    def close(self):
        """Close all thread-local connections. Call on shutdown."""
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None


# Convenience function for backwards compatibility with existing main.py
def get_conn(db_path: str):
    """Create and return a Database instance."""
    return Database(db_path)
