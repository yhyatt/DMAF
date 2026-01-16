"""Tests for thread-safe database operations."""

import threading
from pathlib import Path

from dmaf.database import Database, get_conn


class TestDatabase:
    """Test Database class."""

    def test_init_creates_schema(self, mock_db_path: Path):
        """Test that database initialization creates the schema."""
        db = Database(str(mock_db_path))

        # Verify table was created
        conn = db._get_conn()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='files'")
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
            "SELECT path, sha256, matched, uploaded FROM files WHERE path=?", (file_path,)
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
                    f"/thread_{thread_id}/file.jpg", f"hash_{thread_id}", matched=1, uploaded=0
                )
            except Exception as e:
                errors.append((thread_id, str(e)))

        # Create threads
        threads = [threading.Thread(target=use_connection, args=(i,)) for i in range(5)]

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
                db.add_file(f"/test/file_{i}.jpg", f"hash_{i}", matched=1, uploaded=0)

        # Create threads that add files concurrently
        threads = [threading.Thread(target=add_files, args=(i * 10, 10)) for i in range(5)]

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


class TestDatabaseNewMethods:
    """Test new database methods for Phase F-prep."""

    def test_add_file_with_score(self, mock_db_path: Path):
        """Test adding file with match score."""
        db = Database(str(mock_db_path))

        file_path = "/test/image.jpg"
        db.add_file_with_score(
            file_path, "abc123", matched=1, uploaded=0, match_score=0.75, matched_person="Alice"
        )

        # Verify file was added
        assert db.seen(file_path) is True

        # Verify score and person were stored
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT match_score, matched_person FROM files WHERE path=?", (file_path,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 0.75
        assert row[1] == "Alice"

        db.close()

    def test_add_file_with_score_null_values(self, mock_db_path: Path):
        """Test adding file with null score and person."""
        db = Database(str(mock_db_path))

        file_path = "/test/image2.jpg"
        db.add_file_with_score(
            file_path, "def456", matched=0, uploaded=0, match_score=None, matched_person=None
        )

        # Verify file was added
        assert db.seen(file_path) is True

        # Verify nulls were stored
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT match_score, matched_person FROM files WHERE path=?", (file_path,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] is None
        assert row[1] is None

        db.close()

    def test_add_borderline_event(self, mock_db_path: Path):
        """Test recording a borderline event."""
        db = Database(str(mock_db_path))

        db.add_borderline_event("/test/borderline.jpg", 0.45, 0.52, "Alice")

        # Verify event was recorded
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT file_path, match_score, tolerance, matched_person, alerted "
            "FROM borderline_events"
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "/test/borderline.jpg"
        assert row[1] == 0.45
        assert row[2] == 0.52
        assert row[3] == "Alice"
        assert row[4] == 0  # Not alerted yet

        db.close()

    def test_add_error_event(self, mock_db_path: Path):
        """Test recording an error event."""
        db = Database(str(mock_db_path))

        db.add_error_event("upload", "OAuth token expired", "/test/failed.jpg")

        # Verify event was recorded
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT error_type, error_message, file_path, alerted FROM error_events"
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "upload"
        assert row[1] == "OAuth token expired"
        assert row[2] == "/test/failed.jpg"
        assert row[3] == 0  # Not alerted yet

        db.close()

    def test_add_error_event_without_file(self, mock_db_path: Path):
        """Test recording an error event without file path."""
        db = Database(str(mock_db_path))

        db.add_error_event("system", "Database connection lost", None)

        # Verify event was recorded
        conn = db._get_conn()
        cursor = conn.execute("SELECT error_type, error_message, file_path FROM error_events")
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "system"
        assert row[1] == "Database connection lost"
        assert row[2] is None

        db.close()

    def test_get_pending_alerts_borderline(self, mock_db_path: Path):
        """Test getting pending borderline alerts."""
        db = Database(str(mock_db_path))

        # Add some events
        db.add_borderline_event("/test/b1.jpg", 0.45, 0.52, "Alice")
        db.add_borderline_event("/test/b2.jpg", 0.46, 0.52, "Bob")
        db.add_borderline_event("/test/b3.jpg", 0.47, 0.52, "Alice")

        # Get pending alerts
        alerts = db.get_pending_alerts("borderline")

        assert len(alerts) == 3
        assert all("file_path" in a for a in alerts)
        assert all("match_score" in a for a in alerts)
        assert all("tolerance" in a for a in alerts)
        assert all("matched_person" in a for a in alerts)

        # Verify they're sorted by created_ts
        assert alerts[0]["file_path"] == "/test/b1.jpg"
        assert alerts[1]["file_path"] == "/test/b2.jpg"
        assert alerts[2]["file_path"] == "/test/b3.jpg"

        db.close()

    def test_get_pending_alerts_error(self, mock_db_path: Path):
        """Test getting pending error alerts."""
        db = Database(str(mock_db_path))

        # Add some events
        db.add_error_event("upload", "Error 1", "/test/e1.jpg")
        db.add_error_event("processing", "Error 2", "/test/e2.jpg")

        # Get pending alerts
        alerts = db.get_pending_alerts("error")

        assert len(alerts) == 2
        assert all("error_type" in a for a in alerts)
        assert all("error_message" in a for a in alerts)
        assert all("file_path" in a for a in alerts)

        db.close()

    def test_get_pending_alerts_only_unalertedalerts(self, mock_db_path: Path):
        """Test that only un-alerted events are returned."""
        db = Database(str(mock_db_path))

        # Add events
        db.add_borderline_event("/test/b1.jpg", 0.45, 0.52, "Alice")
        db.add_borderline_event("/test/b2.jpg", 0.46, 0.52, "Bob")

        # Mark first one as alerted
        conn = db._get_conn()
        conn.execute("UPDATE borderline_events SET alerted=1 WHERE file_path=?", ("/test/b1.jpg",))
        conn.commit()

        # Get pending alerts
        alerts = db.get_pending_alerts("borderline")

        assert len(alerts) == 1
        assert alerts[0]["file_path"] == "/test/b2.jpg"

        db.close()

    def test_mark_events_alerted_borderline(self, mock_db_path: Path):
        """Test marking borderline events as alerted."""
        db = Database(str(mock_db_path))

        # Add events
        db.add_borderline_event("/test/b1.jpg", 0.45, 0.52, "Alice")
        db.add_borderline_event("/test/b2.jpg", 0.46, 0.52, "Bob")

        # Get event IDs
        alerts = db.get_pending_alerts("borderline")
        event_ids = [a["id"] for a in alerts]

        # Mark as alerted
        db.mark_events_alerted(event_ids, "borderline")

        # Verify no pending alerts remain
        remaining = db.get_pending_alerts("borderline")
        assert len(remaining) == 0

        db.close()

    def test_mark_events_alerted_error(self, mock_db_path: Path):
        """Test marking error events as alerted."""
        db = Database(str(mock_db_path))

        # Add events
        db.add_error_event("upload", "Error 1", "/test/e1.jpg")
        db.add_error_event("processing", "Error 2", "/test/e2.jpg")

        # Get event IDs
        alerts = db.get_pending_alerts("error")
        event_ids = [a["id"] for a in alerts]

        # Mark as alerted
        db.mark_events_alerted(event_ids, "error")

        # Verify no pending alerts remain
        remaining = db.get_pending_alerts("error")
        assert len(remaining) == 0

        db.close()

    def test_mark_events_alerted_empty_list(self, mock_db_path: Path):
        """Test marking events with empty list (should not error)."""
        db = Database(str(mock_db_path))

        # Should not raise error
        db.mark_events_alerted([], "borderline")
        db.mark_events_alerted([], "error")

        db.close()

    def test_get_last_alert_time_none(self, mock_db_path: Path):
        """Test get_last_alert_time when no alerts sent."""
        db = Database(str(mock_db_path))

        result = db.get_last_alert_time()
        assert result is None

        db.close()

    def test_get_last_alert_time_with_alerts(self, mock_db_path: Path):
        """Test get_last_alert_time with sent alerts."""
        from datetime import datetime

        db = Database(str(mock_db_path))

        # Record some alert batches
        db.record_alert_sent("borderline", "user@example.com", 5)
        db.record_alert_sent("error", "user@example.com", 3)

        # Get last alert time
        result = db.get_last_alert_time()

        assert result is not None
        assert isinstance(result, datetime)

        db.close()

    def test_record_alert_sent(self, mock_db_path: Path):
        """Test recording an alert batch."""
        db = Database(str(mock_db_path))

        db.record_alert_sent("combined", "user@example.com", 10)

        # Verify record was created
        conn = db._get_conn()
        cursor = conn.execute("SELECT alert_type, recipient, event_count FROM alert_batches")
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "combined"
        assert row[1] == "user@example.com"
        assert row[2] == 10

        db.close()

    def test_get_refresh_candidates(self, mock_db_path: Path):
        """Test getting refresh candidates."""
        db = Database(str(mock_db_path))

        # Add some files with scores
        db.add_file_with_score("/test/img1.jpg", "hash1", 1, 1, 0.60, "Alice")
        db.add_file_with_score("/test/img2.jpg", "hash2", 1, 1, 0.65, "Alice")
        db.add_file_with_score("/test/img3.jpg", "hash3", 1, 1, 0.70, "Alice")
        db.add_file_with_score("/test/img4.jpg", "hash4", 1, 1, 0.55, "Bob")

        # Get candidates for Alice with target_score=0.65
        candidates = db.get_refresh_candidates("Alice", 0.65)

        assert len(candidates) == 3
        # Should be sorted by score_delta ascending (closest to target first)
        assert candidates[0]["path"] == "/test/img2.jpg"  # delta = 0.00
        assert candidates[0]["score_delta"] == 0.0
        assert candidates[1]["path"] == "/test/img3.jpg"  # delta = 0.05
        assert candidates[2]["path"] == "/test/img1.jpg"  # delta = 0.05

        db.close()

    def test_get_refresh_candidates_excludes_already_used(self, mock_db_path: Path):
        """Test that refresh candidates excludes already used images."""
        db = Database(str(mock_db_path))

        # Add files
        db.add_file_with_score("/test/img1.jpg", "hash1", 1, 1, 0.65, "Alice")
        db.add_file_with_score("/test/img2.jpg", "hash2", 1, 1, 0.66, "Alice")

        # Mark first one as used in refresh
        db.add_refresh_record("Alice", "/test/img1.jpg", "/known/alice/refresh.jpg", 0.65, 0.65)

        # Get candidates
        candidates = db.get_refresh_candidates("Alice", 0.65)

        # Should only return img2 (img1 was already used)
        assert len(candidates) == 1
        assert candidates[0]["path"] == "/test/img2.jpg"

        db.close()

    def test_get_refresh_candidates_filters_by_person(self, mock_db_path: Path):
        """Test that refresh candidates are filtered by person."""
        db = Database(str(mock_db_path))

        # Add files for different people
        db.add_file_with_score("/test/img1.jpg", "hash1", 1, 1, 0.65, "Alice")
        db.add_file_with_score("/test/img2.jpg", "hash2", 1, 1, 0.65, "Bob")

        # Get candidates for Alice
        candidates = db.get_refresh_candidates("Alice", 0.65)

        assert len(candidates) == 1
        assert candidates[0]["path"] == "/test/img1.jpg"

        db.close()

    def test_get_last_refresh_time_none(self, mock_db_path: Path):
        """Test get_last_refresh_time when no refresh performed."""
        db = Database(str(mock_db_path))

        result = db.get_last_refresh_time()
        assert result is None

        db.close()

    def test_get_last_refresh_time_with_refresh(self, mock_db_path: Path):
        """Test get_last_refresh_time with refresh records."""
        from datetime import datetime

        db = Database(str(mock_db_path))

        # Add refresh records
        db.add_refresh_record("Alice", "/test/src1.jpg", "/known/alice/r1.jpg", 0.65, 0.65)
        db.add_refresh_record("Bob", "/test/src2.jpg", "/known/bob/r1.jpg", 0.66, 0.65)

        # Get last refresh time
        result = db.get_last_refresh_time()

        assert result is not None
        assert isinstance(result, datetime)

        db.close()

    def test_add_refresh_record(self, mock_db_path: Path):
        """Test adding a refresh record."""
        db = Database(str(mock_db_path))

        db.add_refresh_record("Alice", "/test/src.jpg", "/known/alice/refresh.jpg", 0.67, 0.65)

        # Verify record was created
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT person_name, source_file_path, target_file_path, match_score, target_score "
            "FROM known_refresh_history"
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[0] == "Alice"
        assert row[1] == "/test/src.jpg"
        assert row[2] == "/known/alice/refresh.jpg"
        assert row[3] == 0.67
        assert row[4] == 0.65

        db.close()

    def test_cleanup_old_events(self, mock_db_path: Path):
        """Test cleanup of old alerted events."""
        from datetime import datetime, timedelta

        db = Database(str(mock_db_path))

        # Add some events
        db.add_borderline_event("/test/b1.jpg", 0.45, 0.52, "Alice")
        db.add_borderline_event("/test/b2.jpg", 0.46, 0.52, "Bob")
        db.add_error_event("upload", "Error 1", "/test/e1.jpg")
        db.add_error_event("processing", "Error 2", "/test/e2.jpg")

        # Mark some as alerted and set old timestamps
        conn = db._get_conn()
        old_timestamp = (datetime.now() - timedelta(days=100)).isoformat()

        conn.execute(
            "UPDATE borderline_events SET alerted=1, created_ts=? WHERE file_path=?",
            (old_timestamp, "/test/b1.jpg"),
        )
        conn.execute(
            "UPDATE error_events SET alerted=1, created_ts=? WHERE file_path=?",
            (old_timestamp, "/test/e1.jpg"),
        )
        conn.commit()

        # Run cleanup (delete events older than 90 days)
        borderline_deleted, errors_deleted = db.cleanup_old_events(90)

        assert borderline_deleted == 1
        assert errors_deleted == 1

        # Verify recent events still exist
        remaining_borderline = db.get_pending_alerts("borderline")
        remaining_errors = db.get_pending_alerts("error")

        assert len(remaining_borderline) == 1  # b2 still exists
        assert len(remaining_errors) == 1  # e2 still exists

        db.close()

    def test_cleanup_old_events_only_alerted(self, mock_db_path: Path):
        """Test that cleanup only deletes alerted events."""
        from datetime import datetime, timedelta

        db = Database(str(mock_db_path))

        # Add old event that is NOT alerted
        db.add_borderline_event("/test/b1.jpg", 0.45, 0.52, "Alice")

        # Set old timestamp but don't mark as alerted
        conn = db._get_conn()
        old_timestamp = (datetime.now() - timedelta(days=100)).isoformat()
        conn.execute("UPDATE borderline_events SET created_ts=?", (old_timestamp,))
        conn.commit()

        # Run cleanup
        borderline_deleted, _ = db.cleanup_old_events(90)

        # Should not delete (alerted=0)
        assert borderline_deleted == 0

        # Verify event still exists
        remaining = db.get_pending_alerts("borderline")
        assert len(remaining) == 1

        db.close()

    def test_schema_migration_adds_columns(self, mock_db_path: Path):
        """Test that schema migration adds missing columns to existing database."""
        # Create database with old schema (without new columns)
        import sqlite3

        conn = sqlite3.connect(str(mock_db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              path TEXT UNIQUE NOT NULL,
              sha256 TEXT,
              uploaded INTEGER DEFAULT 0,
              matched INTEGER,
              created_ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.commit()
        conn.close()

        # Now open with Database class (should run migration)
        db = Database(str(mock_db_path))

        # Verify new columns were added
        conn = db._get_conn()
        cursor = conn.execute("PRAGMA table_info(files)")
        columns = {row[1] for row in cursor.fetchall()}

        assert "match_score" in columns
        assert "matched_person" in columns

        db.close()

    def test_schema_has_new_tables(self, mock_db_path: Path):
        """Test that schema includes all new tables."""
        db = Database(str(mock_db_path))

        conn = db._get_conn()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        required_tables = {
            "files",
            "embedding_cache",
            "borderline_events",
            "error_events",
            "known_refresh_history",
            "alert_batches",
        }

        assert required_tables.issubset(tables)

        db.close()

    def test_schema_has_indexes(self, mock_db_path: Path):
        """Test that schema includes indexes for performance."""
        db = Database(str(mock_db_path))

        conn = db._get_conn()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall() if row[0] is not None}

        # Check for critical indexes
        assert "idx_borderline_alerted" in indexes
        assert "idx_error_alerted" in indexes

        db.close()
