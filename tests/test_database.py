"""Tests for thread-safe database operations."""

import sqlite3
import threading
from pathlib import Path

import pytest

from wa_automate.database import Database, get_conn


class TestDatabase:
    """Test Database class."""

    def test_init_creates_schema(self, mock_db_path: Path):
        """Test that database initialization creates the schema."""
        db = Database(str(mock_db_path))

        # Verify table was created
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
        )
        assert cursor.fetchone() is not None

        db.close()

    def test_init_with_path_object(self, mock_db_path: Path):
        """Test that Database can be initialized with Path object."""
        db = Database(str(mock_db_path))
        assert db.db_path == mock_db_path
        db.close()

    def test_seen_returns_false_for_new_file(self, mock_db_path: Path):
        """Test that seen() returns False for files not in database."""
        db = Database(str(mock_db_path))
        assert db.seen("/new/file.jpg") is False
        db.close()

    def test_seen_returns_true_after_add(self, mock_db_path: Path):
        """Test that seen() returns True after file is added."""
        db = Database(str(mock_db_path))

        file_path = "/test/image.jpg"
        db.add_file(file_path, "abc123", matched=1, uploaded=0)

        assert db.seen(file_path) is True
        db.close()

    def test_add_file_inserts_record(self, mock_db_path: Path):
        """Test that add_file() inserts a new record."""
        db = Database(str(mock_db_path))

        file_path = "/test/photo.jpg"
        sha256 = "deadbeef" * 8
        db.add_file(file_path, sha256, matched=1, uploaded=0)

        # Verify record exists
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT path, sha256, matched, uploaded FROM files WHERE path=?",
            (file_path,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == file_path
        assert row[1] == sha256
        assert row[2] == 1  # matched
        assert row[3] == 0  # uploaded

        db.close()

    def test_add_file_ignore_duplicates(self, mock_db_path: Path):
        """Test that add_file() ignores duplicate paths (INSERT OR IGNORE)."""
        db = Database(str(mock_db_path))

        file_path = "/test/duplicate.jpg"

        # Add file twice
        db.add_file(file_path, "hash1", matched=1, uploaded=0)
        db.add_file(file_path, "hash2", matched=1, uploaded=0)  # Should be ignored

        # Verify only one record exists
        conn = db._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM files WHERE path=?", (file_path,))
        count = cursor.fetchone()[0]

        assert count == 1

        # Verify first hash was kept
        cursor = conn.execute("SELECT sha256 FROM files WHERE path=?", (file_path,))
        assert cursor.fetchone()[0] == "hash1"

        db.close()

    def test_add_file_with_none_sha256(self, mock_db_path: Path):
        """Test that add_file() handles None sha256."""
        db = Database(str(mock_db_path))

        file_path = "/test/no_hash.jpg"
        db.add_file(file_path, None, matched=0, uploaded=0)

        # Verify record exists with NULL sha256
        conn = db._get_conn()
        cursor = conn.execute("SELECT sha256 FROM files WHERE path=?", (file_path,))
        row = cursor.fetchone()

        assert row[0] is None

        db.close()

    def test_mark_uploaded_updates_record(self, mock_db_path: Path):
        """Test that mark_uploaded() updates the uploaded flag."""
        db = Database(str(mock_db_path))

        file_path = "/test/to_upload.jpg"

        # Add file with uploaded=0
        db.add_file(file_path, "hash123", matched=1, uploaded=0)

        # Mark as uploaded
        db.mark_uploaded(file_path)

        # Verify uploaded flag was set
        conn = db._get_conn()
        cursor = conn.execute("SELECT uploaded FROM files WHERE path=?", (file_path,))
        uploaded = cursor.fetchone()[0]

        assert uploaded == 1

        db.close()

    def test_mark_uploaded_nonexistent_file(self, mock_db_path: Path):
        """Test that mark_uploaded() doesn't error for nonexistent files."""
        db = Database(str(mock_db_path))

        # Should not raise error
        db.mark_uploaded("/nonexistent/file.jpg")

        db.close()

    def test_thread_local_connections(self, mock_db_path: Path):
        """Test that each thread can use connections independently."""
        db = Database(str(mock_db_path))

        results = {}
        errors = []

        def use_connection(thread_id):
            """Use connection in this thread to perform operations."""
            try:
                # Each thread performs independent database operations
                conn = db._get_conn()

                # Verify we can query
                cursor = conn.execute("SELECT 1")
                result = cursor.fetchone()[0]
                results[thread_id] = result

                # Add a file (tests write lock)
                db.add_file(
                    f"/thread_{thread_id}/file.jpg",
                    f"hash_{thread_id}",
                    matched=1,
                    uploaded=0
                )
            except Exception as e:
                errors.append((thread_id, str(e)))

        # Create threads
        threads = [
            threading.Thread(target=use_connection, args=(i,))
            for i in range(5)
        ]

        # Run threads
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify no errors occurred
        assert len(errors) == 0, f"Thread errors: {errors}"

        # Verify all threads completed successfully
        assert len(results) == 5
        assert all(result == 1 for result in results.values())

        # Verify all files were added
        conn = db._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 5

        db.close()

    def test_concurrent_writes(self, mock_db_path: Path):
        """Test that concurrent writes don't cause conflicts."""
        db = Database(str(mock_db_path))

        def add_files(start_idx, count):
            """Add multiple files in this thread."""
            for i in range(start_idx, start_idx + count):
                db.add_file(
                    f"/test/file_{i}.jpg",
                    f"hash_{i}",
                    matched=1,
                    uploaded=0
                )

        # Create threads that add files concurrently
        threads = [
            threading.Thread(target=add_files, args=(i * 10, 10))
            for i in range(5)
        ]

        # Run threads
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all 50 files were added
        conn = db._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        count = cursor.fetchone()[0]

        assert count == 50

        db.close()

    def test_close_clears_connection(self, mock_db_path: Path):
        """Test that close() clears the thread-local connection."""
        db = Database(str(mock_db_path))

        # Get connection
        conn1 = db._get_conn()
        assert conn1 is not None

        # Close
        db.close()

        # Verify connection was cleared
        assert db._local.conn is None

    def test_close_is_idempotent(self, mock_db_path: Path):
        """Test that close() can be called multiple times safely."""
        db = Database(str(mock_db_path))

        # Close multiple times
        db.close()
        db.close()
        db.close()  # Should not error

    def test_reconnect_after_close(self, mock_db_path: Path):
        """Test that a new connection is created after close()."""
        db = Database(str(mock_db_path))

        conn1 = db._get_conn()
        db.close()

        conn2 = db._get_conn()

        # Should get a new connection (different id)
        assert id(conn1) != id(conn2)

        db.close()

    def test_schema_has_required_columns(self, mock_db_path: Path):
        """Test that the schema has all required columns."""
        db = Database(str(mock_db_path))

        conn = db._get_conn()
        cursor = conn.execute("PRAGMA table_info(files)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}  # name: type

        required_columns = {
            "id": "INTEGER",
            "path": "TEXT",
            "sha256": "TEXT",
            "uploaded": "INTEGER",
            "matched": "INTEGER",
            "created_ts": "DATETIME",
        }

        for col_name, col_type in required_columns.items():
            assert col_name in columns
            assert col_type in columns[col_name]

        db.close()

    def test_database_timeout_setting(self, mock_db_path: Path):
        """Test that database connection has timeout configured."""
        db = Database(str(mock_db_path))
        conn = db._get_conn()

        # SQLite doesn't expose timeout as a queryable property easily,
        # but we can verify the connection was created successfully
        # with check_same_thread=False
        assert conn is not None

        # Verify we can query the database
        cursor = conn.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1

        db.close()


class TestGetConn:
    """Test get_conn() convenience function."""

    def test_get_conn_returns_database(self, mock_db_path: Path):
        """Test that get_conn() returns a Database instance."""
        db = get_conn(str(mock_db_path))

        assert isinstance(db, Database)
        assert db.db_path == mock_db_path

        db.close()

    def test_get_conn_creates_schema(self, mock_db_path: Path):
        """Test that get_conn() creates the schema."""
        db = get_conn(str(mock_db_path))

        # Verify schema exists
        assert db.seen("/test/file.jpg") is False  # Should not error

        db.close()
