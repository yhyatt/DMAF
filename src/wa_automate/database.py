# database logic
import hashlib
import sqlite3
import threading
from pathlib import Path

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
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,  # Wait up to 30s if database is locked
            )
        return self._local.conn

    def seen(self, path: str) -> bool:
        """Check if a file path has been processed before."""
        conn = self._get_conn()
        cur = conn.execute("SELECT 1 FROM files WHERE path=?", (path,))
        return cur.fetchone() is not None

    def add_file(self, path: str, sha256: str | None, matched: int, uploaded: int):
        """Add a new file record to the database."""
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO files(path, sha256, matched, uploaded) VALUES(?,?,?,?)",
                (path, sha256, matched, uploaded),
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
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None


class FirestoreDatabase:
    """
    Firestore backend for cloud deployments.

    Uses Google Cloud Firestore for serverless state storage.
    Compatible with Database interface (seen, add_file, mark_uploaded, close).
    """

    def __init__(self, project_id: str, collection: str = "dmaf_files"):
        """
        Initialize Firestore client.

        Args:
            project_id: GCP project ID
            collection: Firestore collection name (default: dmaf_files)
        """
        try:
            from google.cloud import firestore
        except ImportError as e:
            raise ImportError(
                "google-cloud-firestore not installed. "
                "Install with: pip install google-cloud-firestore"
            ) from e

        self.db = firestore.Client(project=project_id)
        self.collection = self.db.collection(collection)

    def _hash_path(self, path: str) -> str:
        """Hash file path to create Firestore document ID."""
        return hashlib.sha256(path.encode()).hexdigest()[:32]

    def seen(self, path: str) -> bool:
        """Check if a file path has been processed before."""
        doc_id = self._hash_path(path)
        doc = self.collection.document(doc_id).get()
        return doc.exists

    def add_file(self, path: str, sha256: str | None, matched: int, uploaded: int):
        """Add a new file record to Firestore."""
        from google.cloud import firestore

        doc_id = self._hash_path(path)
        self.collection.document(doc_id).set(
            {
                "path": path,
                "sha256": sha256,
                "matched": matched,
                "uploaded": uploaded,
                "created_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,  # Update if exists (like INSERT OR IGNORE)
        )

    def mark_uploaded(self, path: str):
        """Mark a file as uploaded to Google Photos."""
        doc_id = self._hash_path(path)
        self.collection.document(doc_id).update({"uploaded": 1})

    def close(self):
        """No-op for Firestore (connections managed automatically)."""
        pass


def get_conn(db_path: str):
    """
    Create and return a Database instance (SQLite).

    For backwards compatibility. For new code, use get_database().
    """
    return Database(db_path)


def get_database(backend: str, **kwargs):
    """
    Factory function to create appropriate database backend.

    Args:
        backend: "sqlite" or "firestore"
        **kwargs: Backend-specific arguments:
            For SQLite: db_path (str)
            For Firestore: project_id (str), collection (str, optional)

    Returns:
        Database or FirestoreDatabase instance with compatible interface

    Examples:
        # SQLite backend
        db = get_database("sqlite", db_path="./state.sqlite3")

        # Firestore backend
        db = get_database("firestore", project_id="my-project", collection="dmaf_files")
    """
    if backend == "sqlite":
        return Database(kwargs["db_path"])
    elif backend == "firestore":
        return FirestoreDatabase(
            project_id=kwargs["project_id"],
            collection=kwargs.get("collection", "dmaf_files"),
        )
    else:
        raise ValueError(f"Unknown database backend: {backend}")
