# database logic
import hashlib
import json
import pickle
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE,
  sha256 TEXT,
  uploaded INTEGER DEFAULT 0,
  matched INTEGER,
  created_ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  match_score REAL,
  matched_person TEXT
);

CREATE TABLE IF NOT EXISTS embedding_cache(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cache_key TEXT UNIQUE,
  files_hash TEXT NOT NULL,
  encodings_blob BLOB NOT NULL,
  people_json TEXT NOT NULL,
  created_ts DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS borderline_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT NOT NULL,
  match_score REAL NOT NULL,
  tolerance REAL NOT NULL,
  matched_person TEXT,
  alerted INTEGER DEFAULT 0,
  created_ts DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_borderline_alerted ON borderline_events(alerted);

CREATE TABLE IF NOT EXISTS error_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  error_type TEXT NOT NULL,
  error_message TEXT NOT NULL,
  file_path TEXT,
  alerted INTEGER DEFAULT 0,
  created_ts DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_error_alerted ON error_events(alerted);

CREATE TABLE IF NOT EXISTS known_refresh_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_name TEXT NOT NULL,
  source_file_path TEXT NOT NULL,
  target_file_path TEXT NOT NULL,
  match_score REAL NOT NULL,
  target_score REAL NOT NULL,
  created_ts DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alert_batches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_type TEXT NOT NULL,
  recipient TEXT NOT NULL,
  event_count INTEGER NOT NULL,
  sent_ts DATETIME DEFAULT CURRENT_TIMESTAMP
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
        conn.executescript(SCHEMA)  # Use executescript for multiple statements
        conn.commit()

        # Run migrations for existing databases
        self._migrate_schema(conn)

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0,  # Wait up to 30s if database is locked
            )
        conn: sqlite3.Connection = self._local.conn
        return conn

    def _migrate_schema(self, conn: sqlite3.Connection):
        """
        Migrate existing databases to add new columns.

        SQLite doesn't support all ALTER TABLE operations, but supports ADD COLUMN.
        This method checks for missing columns and adds them if needed.
        """
        with self._write_lock:
            # Check if files table has new columns
            cursor = conn.execute("PRAGMA table_info(files)")
            columns = {row[1] for row in cursor.fetchall()}

            if "match_score" not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN match_score REAL")

            if "matched_person" not in columns:
                conn.execute("ALTER TABLE files ADD COLUMN matched_person TEXT")

            conn.commit()

    def seen(self, path: str) -> bool:
        """Check if a file path has been processed before."""
        conn = self._get_conn()
        cur = conn.execute("SELECT 1 FROM files WHERE path=?", (path,))
        result = cur.fetchone()
        return result is not None

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

    def add_file_with_score(
        self,
        path: str,
        sha256: str | None,
        matched: int,
        uploaded: int,
        match_score: float | None = None,
        matched_person: str | None = None,
    ):
        """
        Add a new file record with match score information.

        Args:
            path: File path
            sha256: SHA256 hash of file content
            matched: 1 if face matched, 0 otherwise
            uploaded: 1 if uploaded to Google Photos, 0 otherwise
            match_score: Best similarity score (0.0-1.0)
            matched_person: Name of person matched (if any)
        """
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO files(path, sha256, matched, uploaded, "
                "match_score, matched_person) VALUES(?,?,?,?,?,?)",
                (path, sha256, matched, uploaded, match_score, matched_person),
            )
            conn.commit()

    def add_borderline_event(
        self,
        file_path: str,
        match_score: float,
        tolerance: float,
        matched_person: str | None,
    ):
        """
        Record a borderline recognition event.

        Args:
            file_path: Path to image file
            match_score: Similarity score (close to but below threshold)
            tolerance: Configured tolerance threshold
            matched_person: Closest matching person name
        """
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO borderline_events(file_path, match_score, tolerance, matched_person) "
                "VALUES(?,?,?,?)",
                (file_path, match_score, tolerance, matched_person),
            )
            conn.commit()

    def add_error_event(
        self,
        error_type: str,
        error_message: str,
        file_path: str | None = None,
    ):
        """
        Record a processing or upload error event.

        Args:
            error_type: Type of error ('processing', 'upload', 'auth', 'system')
            error_message: Error message text
            file_path: Optional path to file that caused error
        """
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO error_events(error_type, error_message, file_path) VALUES(?,?,?)",
                (error_type, error_message, file_path),
            )
            conn.commit()

    def get_cached_embeddings(
        self, cache_key: str, files_hash: str
    ) -> tuple[dict[str, list[np.ndarray]], list[str]] | None:
        """
        Retrieve cached face embeddings if they match the current files.

        Args:
            cache_key: Unique key based on backend + parameters
            files_hash: Hash of known_people directory state (file paths + mtimes)

        Returns:
            (encodings_dict, people_list) if cache valid, None if cache miss/invalid
        """
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT files_hash, encodings_blob, people_json FROM embedding_cache WHERE cache_key=?",
            (cache_key,),
        )
        row = cur.fetchone()

        if row is None:
            return None

        cached_files_hash, encodings_blob, people_json = row

        # Validate: files must match exactly
        if cached_files_hash != files_hash:
            return None

        # Deserialize
        try:
            encodings: dict[str, list[np.ndarray]] = pickle.loads(encodings_blob)
            people: list[str] = json.loads(people_json)
            return encodings, people
        except (pickle.UnpicklingError, json.JSONDecodeError):
            return None

    def save_cached_embeddings(
        self,
        cache_key: str,
        files_hash: str,
        encodings: dict[str, list[np.ndarray]],
        people: list[str],
    ):
        """
        Save face embeddings to cache.

        Args:
            cache_key: Unique key based on backend + parameters
            files_hash: Hash of known_people directory state
            encodings: Dictionary mapping person names to face encodings
            people: List of person names
        """
        with self._write_lock:
            # Serialize
            encodings_blob = pickle.dumps(encodings)
            people_json = json.dumps(people)

            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache("
                "cache_key, files_hash, encodings_blob, people_json) "
                "VALUES(?,?,?,?)",
                (cache_key, files_hash, encodings_blob, people_json),
            )
            conn.commit()

    def get_pending_alerts(self, alert_type: str) -> list[dict]:
        """
        Get un-alerted events of specified type.

        Args:
            alert_type: 'borderline' or 'error'

        Returns:
            List of event dictionaries with all fields
        """
        conn = self._get_conn()

        if alert_type == "borderline":
            cur = conn.execute(
                "SELECT id, file_path, match_score, tolerance, matched_person, created_ts "
                "FROM borderline_events WHERE alerted=0 ORDER BY created_ts ASC"
            )
            rows = cur.fetchall()
            return [
                {
                    "id": row[0],
                    "file_path": row[1],
                    "match_score": row[2],
                    "tolerance": row[3],
                    "matched_person": row[4],
                    "created_ts": row[5],
                }
                for row in rows
            ]
        elif alert_type == "error":
            cur = conn.execute(
                "SELECT id, error_type, error_message, file_path, created_ts "
                "FROM error_events WHERE alerted=0 ORDER BY created_ts ASC"
            )
            rows = cur.fetchall()
            return [
                {
                    "id": row[0],
                    "error_type": row[1],
                    "error_message": row[2],
                    "file_path": row[3],
                    "created_ts": row[4],
                }
                for row in rows
            ]
        else:
            raise ValueError(f"Unknown alert_type: {alert_type}")

    def mark_events_alerted(self, event_ids: list[int], alert_type: str):
        """
        Mark events as included in an alert.

        Args:
            event_ids: List of event IDs to mark
            alert_type: 'borderline' or 'error'
        """
        if not event_ids:
            return

        with self._write_lock:
            conn = self._get_conn()
            table = "borderline_events" if alert_type == "borderline" else "error_events"

            # Build placeholders for SQL IN clause
            placeholders = ",".join("?" * len(event_ids))
            conn.execute(
                f"UPDATE {table} SET alerted=1 WHERE id IN ({placeholders})",
                event_ids,
            )
            conn.commit()

    def get_last_alert_time(self) -> datetime | None:
        """
        Get timestamp of last sent alert.

        Returns None if no alerts have been sent.
        """
        conn = self._get_conn()
        cur = conn.execute("SELECT MAX(sent_ts) FROM alert_batches")
        result = cur.fetchone()[0]
        if result:
            return datetime.fromisoformat(result)
        return None

    def record_alert_sent(
        self,
        alert_type: str,
        recipient: str,
        event_count: int,
    ):
        """
        Record that an alert batch was sent.

        Args:
            alert_type: Type of alert ('borderline', 'error', 'combined')
            recipient: Email address that received the alert
            event_count: Number of events included in alert
        """
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO alert_batches(alert_type, recipient, event_count) VALUES(?,?,?)",
                (alert_type, recipient, event_count),
            )
            conn.commit()

    def get_refresh_candidates(
        self,
        person_name: str,
        target_score: float,
    ) -> list[dict]:
        """
        Get candidate files for known_people refresh.

        Finds uploaded files where:
        - matched=1 AND uploaded=1
        - matched_person = person_name
        - match_score IS NOT NULL
        - Not already used in refresh_history

        Returns candidates sorted by abs(match_score - target_score) ascending.

        Args:
            person_name: Name of person to find candidates for
            target_score: Target score for selection (e.g., 0.65)

        Returns:
            List of candidate dictionaries with file info and score_delta
        """
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT f.id, f.path, f.match_score, f.sha256,
                   ABS(f.match_score - ?) AS score_delta
            FROM files f
            LEFT JOIN known_refresh_history r ON f.path = r.source_file_path
            WHERE f.matched=1
              AND f.uploaded=1
              AND f.matched_person=?
              AND f.match_score IS NOT NULL
              AND r.id IS NULL
            ORDER BY score_delta ASC
            """,
            (target_score, person_name),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "path": row[1],
                "match_score": row[2],
                "sha256": row[3],
                "score_delta": row[4],
            }
            for row in rows
        ]

    def get_last_refresh_time(self) -> datetime | None:
        """
        Get timestamp of last refresh operation.

        Returns None if no refresh has ever been performed.
        """
        conn = self._get_conn()
        cur = conn.execute("SELECT MAX(created_ts) FROM known_refresh_history")
        result = cur.fetchone()[0]
        if result:
            return datetime.fromisoformat(result)
        return None

    def add_refresh_record(
        self,
        person_name: str,
        source_file_path: str,
        target_file_path: str,
        match_score: float,
        target_score: float,
    ):
        """
        Record a refresh operation.

        Args:
            person_name: Name of person
            source_file_path: Original uploaded file path
            target_file_path: Path in known_people directory
            match_score: Score when image was originally matched
            target_score: Configured target score
        """
        with self._write_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO known_refresh_history(person_name, source_file_path, "
                "target_file_path, match_score, target_score) VALUES(?,?,?,?,?)",
                (person_name, source_file_path, target_file_path, match_score, target_score),
            )
            conn.commit()

    def cleanup_old_events(self, retention_days: int) -> tuple[int, int]:
        """
        Delete alerted events older than retention_days.

        Only deletes events that have already been alerted (alerted=1).
        This prevents unbounded database growth while preserving recent events.

        Args:
            retention_days: Delete events older than this many days

        Returns:
            Tuple of (borderline_deleted_count, errors_deleted_count)
        """
        cutoff_ts = datetime.now() - timedelta(days=retention_days)
        cutoff_str = cutoff_ts.isoformat()

        with self._write_lock:
            conn = self._get_conn()

            # Delete old borderline events (only alerted ones)
            cur = conn.execute(
                "DELETE FROM borderline_events WHERE alerted=1 AND created_ts < ?",
                (cutoff_str,),
            )
            borderline_count = cur.rowcount

            # Delete old error events (only alerted ones)
            cur = conn.execute(
                "DELETE FROM error_events WHERE alerted=1 AND created_ts < ?",
                (cutoff_str,),
            )
            errors_count = cur.rowcount

            conn.commit()

        return (borderline_count, errors_count)

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
        return bool(doc.exists)

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
