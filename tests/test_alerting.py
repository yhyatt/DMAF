"""Tests for alerting functionality."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from dmaf.alerting import AlertManager
from dmaf.alerting.email_sender import EmailSender
from dmaf.alerting.templates import (
    format_borderline_alert,
    format_combined_alert,
    format_error_alert,
    format_refresh_alert,
)
from dmaf.config import AlertSettings, SmtpSettings
from dmaf.database import Database


class TestEmailSender:
    """Test EmailSender class."""

    def test_init(self):
        """Test EmailSender initialization."""
        smtp_config = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )

        sender = EmailSender(smtp_config)

        assert sender.config == smtp_config

    @patch("dmaf.alerting.email_sender.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp):
        """Test successful email sending."""
        smtp_config = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            sender_email="sender@example.com",
            use_tls=True,
        )

        sender = EmailSender(smtp_config)

        result = sender.send_email(
            recipients=["recipient@example.com"],
            subject="Test Subject",
            body_text="Test body",
        )

        assert result is True
        mock_smtp.assert_called_once_with("smtp.example.com", 587)

    @patch("dmaf.alerting.email_sender.smtplib.SMTP")
    def test_send_email_with_html(self, mock_smtp):
        """Test sending email with HTML body."""
        smtp_config = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )

        sender = EmailSender(smtp_config)

        result = sender.send_email(
            recipients=["recipient@example.com"],
            subject="Test Subject",
            body_text="Test body",
            body_html="<html><body>Test HTML body</body></html>",
        )

        assert result is True

    @patch("dmaf.alerting.email_sender.smtplib.SMTP")
    def test_send_email_multiple_recipients(self, mock_smtp):
        """Test sending email to multiple recipients."""
        smtp_config = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )

        sender = EmailSender(smtp_config)

        result = sender.send_email(
            recipients=["user1@example.com", "user2@example.com"],
            subject="Test Subject",
            body_text="Test body",
        )

        assert result is True

    def test_send_email_no_recipients(self):
        """Test that sending with no recipients returns False."""
        smtp_config = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )

        sender = EmailSender(smtp_config)

        result = sender.send_email(recipients=[], subject="Test Subject", body_text="Test body")

        assert result is False

    @patch("dmaf.alerting.email_sender.smtplib.SMTP")
    def test_send_email_smtp_error(self, mock_smtp):
        """Test handling of SMTP errors."""
        mock_smtp.side_effect = Exception("SMTP connection failed")

        smtp_config = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )

        sender = EmailSender(smtp_config)

        result = sender.send_email(
            recipients=["recipient@example.com"],
            subject="Test Subject",
            body_text="Test body",
        )

        assert result is False


class TestEmailTemplates:
    """Test email template formatting."""

    def test_format_borderline_alert_single(self):
        """Test formatting borderline alert with single event."""
        events = [
            {
                "file_path": "/test/img1.jpg",
                "match_score": 0.45,
                "tolerance": 0.52,
                "matched_person": "Alice",
                "created_ts": "2024-01-15 14:30:22",
            }
        ]

        text, html = format_borderline_alert(events)

        assert "1 image" in text
        assert "/test/img1.jpg" in text
        assert "0.45" in text
        assert "0.48" in text  # threshold = 1.0 - 0.52
        assert "Alice" in text

    def test_format_borderline_alert_multiple(self):
        """Test formatting borderline alert with multiple events."""
        events = [
            {
                "file_path": f"/test/img{i}.jpg",
                "match_score": 0.45 + i * 0.01,
                "tolerance": 0.52,
                "matched_person": "Alice",
                "created_ts": f"2024-01-15 14:{30 + i}:22",
            }
            for i in range(15)
        ]

        text, html = format_borderline_alert(events)

        assert "15 image" in text
        # Should show first 10
        assert "/test/img0.jpg" in text
        assert "/test/img9.jpg" in text
        # Should indicate more exist
        assert "5 more events" in text

    def test_format_error_alert_single(self):
        """Test formatting error alert with single event."""
        events = [
            {
                "error_type": "upload",
                "error_message": "OAuth token expired",
                "file_path": "/test/failed.jpg",
                "created_ts": "2024-01-15 12:00:05",
            }
        ]

        text, html = format_error_alert(events)

        assert "1 error" in text
        assert "upload" in text
        assert "OAuth token expired" in text
        assert "/test/failed.jpg" in text

    def test_format_error_alert_without_file(self):
        """Test formatting error alert without file path."""
        events = [
            {
                "error_type": "system",
                "error_message": "Database connection lost",
                "file_path": None,
                "created_ts": "2024-01-15 12:00:05",
            }
        ]

        text, html = format_error_alert(events)

        assert "system" in text
        assert "Database connection lost" in text

    def test_format_combined_alert(self):
        """Test formatting combined alert with borderline and errors."""
        borderline_events = [
            {
                "file_path": "/test/b1.jpg",
                "match_score": 0.45,
                "tolerance": 0.52,
                "matched_person": "Alice",
                "created_ts": "2024-01-15 14:30:22",
            }
        ]

        error_events = [
            {
                "error_type": "upload",
                "error_message": "Upload failed",
                "file_path": "/test/e1.jpg",
                "created_ts": "2024-01-15 15:00:00",
            }
        ]

        text, html = format_combined_alert(borderline_events, error_events)

        assert "== ERRORS (1) ==" in text
        assert "== BORDERLINE RECOGNITIONS (1) ==" in text
        assert "upload" in text
        assert "/test/b1.jpg" in text

    def test_format_refresh_alert(self):
        """Test formatting refresh notification."""
        results = [
            {
                "person_name": "Alice",
                "source_file_path": "/uploads/img1.jpg",
                "target_file_path": "/known/alice/refresh_20240115.jpg",
                "match_score": 0.67,
                "target_score": 0.65,
            },
            {
                "person_name": "Bob",
                "source_file_path": "/uploads/img2.jpg",
                "target_file_path": "/known/bob/refresh_20240115.jpg",
                "match_score": 0.64,
                "target_score": 0.65,
            },
        ]

        text, html = format_refresh_alert(results)

        assert "2 new reference image" in text
        assert "Alice" in text
        assert "Bob" in text
        assert "/uploads/img1.jpg" in text
        assert "0.67" in text
        assert "0.65" in text


class TestAlertManager:
    """Test AlertManager class."""

    @pytest.fixture
    def mock_db(self, mock_db_path: Path):
        """Create a mock database for testing."""
        return Database(str(mock_db_path))

    @pytest.fixture
    def alert_config(self):
        """Create alert configuration."""
        smtp = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            sender_email="alerts@example.com",
        )

        return AlertSettings(
            enabled=True,
            recipients=["user@example.com"],
            batch_interval_minutes=60,
            borderline_offset=0.1,
            smtp=smtp,
        )

    def test_init(self, mock_db, alert_config):
        """Test AlertManager initialization."""
        manager = AlertManager(alert_config, mock_db)

        assert manager.config == alert_config
        assert manager.db == mock_db
        assert manager.email_sender is not None

    def test_record_borderline(self, mock_db, alert_config):
        """Test recording borderline event."""
        manager = AlertManager(alert_config, mock_db)

        manager.record_borderline("/test/img.jpg", 0.45, 0.52, "Alice")

        # Verify event was recorded in database
        events = mock_db.get_pending_alerts("borderline")
        assert len(events) == 1
        assert events[0]["file_path"] == "/test/img.jpg"

    def test_record_error(self, mock_db, alert_config):
        """Test recording error event."""
        manager = AlertManager(alert_config, mock_db)

        manager.record_error("upload", "Failed to upload", "/test/img.jpg")

        # Verify event was recorded in database
        events = mock_db.get_pending_alerts("error")
        assert len(events) == 1
        assert events[0]["error_type"] == "upload"

    def test_should_send_alert_no_events(self, mock_db, alert_config):
        """Test should_send_alert returns False when no events."""
        manager = AlertManager(alert_config, mock_db)

        result = manager.should_send_alert()

        assert result is False

    def test_should_send_alert_with_pending_events_first_time(self, mock_db, alert_config):
        """Test should_send_alert returns True for first alert."""
        manager = AlertManager(alert_config, mock_db)

        # Add pending event
        manager.record_borderline("/test/img.jpg", 0.45, 0.52, "Alice")

        result = manager.should_send_alert()

        assert result is True

    def test_should_send_alert_too_soon(self, mock_db, alert_config):
        """Test should_send_alert returns False when called too soon."""
        from datetime import datetime

        manager = AlertManager(alert_config, mock_db)

        # Simulate an alert sent just now
        now = datetime.now()
        conn = mock_db._get_conn()
        conn.execute(
            "INSERT INTO alert_batches(alert_type, recipient, event_count, sent_ts) "
            "VALUES(?,?,?,?)",
            ("borderline", "user@example.com", 1, now.isoformat()),
        )
        conn.commit()

        # Add new pending event
        manager.record_borderline("/test/img.jpg", 0.45, 0.52, "Alice")

        # Check immediately - should be too soon (last alert was just sent)
        result = manager.should_send_alert()

        assert result is False

    def test_should_send_alert_after_interval(self, mock_db, alert_config):
        """Test should_send_alert returns True after interval passes."""
        manager = AlertManager(alert_config, mock_db)

        # Simulate old alert
        old_time = datetime.now() - timedelta(minutes=61)
        conn = mock_db._get_conn()
        conn.execute(
            "INSERT INTO alert_batches(alert_type, recipient, event_count, sent_ts) "
            "VALUES(?,?,?,?)",
            ("borderline", "user@example.com", 1, old_time.isoformat()),
        )
        conn.commit()

        # Add new pending event
        manager.record_borderline("/test/img.jpg", 0.45, 0.52, "Alice")

        result = manager.should_send_alert()

        assert result is True

    @patch("dmaf.alerting.alert_manager.EmailSender.send_email")
    def test_send_pending_alerts_borderline_only(self, mock_send_email, mock_db, alert_config):
        """Test sending pending borderline alerts."""
        mock_send_email.return_value = True

        manager = AlertManager(alert_config, mock_db)

        # Add borderline events
        manager.record_borderline("/test/b1.jpg", 0.45, 0.52, "Alice")
        manager.record_borderline("/test/b2.jpg", 0.46, 0.52, "Bob")

        # Send alerts
        result = manager.send_pending_alerts()

        assert result == 2
        mock_send_email.assert_called_once()

        # Verify subject
        call_args = mock_send_email.call_args
        assert "Borderline" in call_args[0][1]  # Second positional arg is subject

        # Verify no pending alerts remain
        remaining = mock_db.get_pending_alerts("borderline")
        assert len(remaining) == 0

    @patch("dmaf.alerting.alert_manager.EmailSender.send_email")
    def test_send_pending_alerts_errors_only(self, mock_send_email, mock_db, alert_config):
        """Test sending pending error alerts."""
        mock_send_email.return_value = True

        manager = AlertManager(alert_config, mock_db)

        # Add error events
        manager.record_error("upload", "Error 1", "/test/e1.jpg")
        manager.record_error("processing", "Error 2", "/test/e2.jpg")

        # Send alerts
        result = manager.send_pending_alerts()

        assert result == 2
        mock_send_email.assert_called_once()

        # Verify subject
        call_args = mock_send_email.call_args
        assert "Error" in call_args[0][1]  # Second positional arg is subject

    @patch("dmaf.alerting.alert_manager.EmailSender.send_email")
    def test_send_pending_alerts_combined(self, mock_send_email, mock_db, alert_config):
        """Test sending combined alerts."""
        mock_send_email.return_value = True

        manager = AlertManager(alert_config, mock_db)

        # Add both types of events
        manager.record_borderline("/test/b1.jpg", 0.45, 0.52, "Alice")
        manager.record_error("upload", "Error 1", "/test/e1.jpg")

        # Send alerts
        result = manager.send_pending_alerts()

        assert result == 2
        mock_send_email.assert_called_once()

        # Verify subject indicates combined
        call_args = mock_send_email.call_args
        assert "Alert Summary" in call_args[0][1]  # Second positional arg is subject

    @patch("dmaf.alerting.alert_manager.EmailSender.send_email")
    def test_send_pending_alerts_no_events(self, mock_send_email, mock_db, alert_config):
        """Test sending alerts when no pending events."""
        manager = AlertManager(alert_config, mock_db)

        result = manager.send_pending_alerts()

        assert result == 0
        mock_send_email.assert_not_called()

    @patch("dmaf.alerting.alert_manager.EmailSender.send_email")
    def test_send_pending_alerts_email_failure(self, mock_send_email, mock_db, alert_config):
        """Test handling email send failure."""
        mock_send_email.return_value = False

        manager = AlertManager(alert_config, mock_db)

        # Add event
        manager.record_borderline("/test/b1.jpg", 0.45, 0.52, "Alice")

        # Send alerts
        result = manager.send_pending_alerts()

        assert result == 0

        # Verify events remain pending (not marked as alerted)
        remaining = mock_db.get_pending_alerts("borderline")
        assert len(remaining) == 1

    @patch("dmaf.alerting.alert_manager.EmailSender.send_email")
    def test_send_refresh_notification(self, mock_send_email, mock_db, alert_config):
        """Test sending refresh notification."""
        mock_send_email.return_value = True

        manager = AlertManager(alert_config, mock_db)

        refresh_results = [
            {
                "person_name": "Alice",
                "source_file_path": "/uploads/img1.jpg",
                "target_file_path": "/known/alice/refresh.jpg",
                "match_score": 0.67,
                "target_score": 0.65,
            }
        ]

        result = manager.send_refresh_notification(refresh_results)

        assert result is True
        mock_send_email.assert_called_once()

        # Verify subject
        call_args = mock_send_email.call_args
        assert "Known Face Updated" in call_args[0][1]  # Second positional arg is subject

    @patch("dmaf.alerting.alert_manager.EmailSender.send_email")
    def test_send_refresh_notification_empty_results(self, mock_send_email, mock_db, alert_config):
        """Test refresh notification with empty results."""
        manager = AlertManager(alert_config, mock_db)

        result = manager.send_refresh_notification([])

        assert result is False
        mock_send_email.assert_not_called()

    def test_alert_manager_without_smtp(self, mock_db):
        """Test AlertManager with alerting disabled."""
        # When alerting is disabled, SMTP is not required
        config = AlertSettings(enabled=False, recipients=[], smtp=None)

        # Should not raise error during init
        manager = AlertManager(config, mock_db)

        # email_sender will still be None when enabled=False
        # But in practice, when enabled=False, AlertManager won't be created

        # Just verify manager can be created with disabled config
        assert manager is not None
