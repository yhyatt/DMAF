"""
Alert manager for batching and sending email notifications.
"""

import logging
from datetime import datetime, timedelta, timezone

from dmaf.alerting.email_sender import EmailSender
from dmaf.alerting.templates import (
    format_borderline_alert,
    format_combined_alert,
    format_error_alert,
    format_refresh_alert,
)
from dmaf.config import AlertSettings
from dmaf.database import Database

logger = logging.getLogger(__name__)


class AlertManager:
    """Manages alert batching and sending."""

    def __init__(self, config: AlertSettings, db: Database):
        """
        Initialize alert manager.

        Args:
            config: Alert configuration settings
            db: Database connection for storing events
        """
        self.config = config
        self.db = db
        self.email_sender = EmailSender(config.smtp) if config.smtp else None

    def record_borderline(
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
        self.db.add_borderline_event(file_path, match_score, tolerance, matched_person)
        logger.debug(f"Recorded borderline event: {file_path} (score: {match_score:.2f})")

    def record_error(
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
        self.db.add_error_event(error_type, error_message, file_path)
        logger.debug(f"Recorded error event: {error_type} - {error_message}")

    def should_send_alert(self) -> bool:
        """
        Check if enough time has passed to send an alert.

        Returns:
            True if alert should be sent, False otherwise
        """
        last_alert = self.db.get_last_alert_time()

        if last_alert is None:
            # No alerts ever sent - send if there are pending events
            borderline = self.db.get_pending_alerts("borderline")
            errors = self.db.get_pending_alerts("error")
            return len(borderline) > 0 or len(errors) > 0

        # Check if enough time has passed since last alert
        now = datetime.now(timezone.utc)
        time_since_last = now - last_alert
        interval = timedelta(minutes=self.config.batch_interval_minutes)

        if time_since_last < interval:
            return False

        # Enough time has passed - check if there are pending events
        borderline = self.db.get_pending_alerts("borderline")
        errors = self.db.get_pending_alerts("error")
        return len(borderline) > 0 or len(errors) > 0

    def send_pending_alerts(self) -> int:
        """
        Send batched alerts for all pending events.

        Returns:
            Number of events included in sent alerts (0 if no alert sent)
        """
        if not self.email_sender:
            logger.warning("Email sender not configured, skipping alerts")
            return 0

        # Get pending events
        borderline_events = self.db.get_pending_alerts("borderline")
        error_events = self.db.get_pending_alerts("error")

        if not borderline_events and not error_events:
            logger.debug("No pending alerts to send")
            return 0

        total_events = len(borderline_events) + len(error_events)

        # Determine alert type and format content
        if borderline_events and error_events:
            alert_type = "combined"
            subject = (
                f"[DMAF] Alert Summary: {len(error_events)} errors, "
                f"{len(borderline_events)} borderline images"
            )
            body_text, body_html = format_combined_alert(borderline_events, error_events)
        elif error_events:
            alert_type = "error"
            subject = f"[DMAF] Processing Errors ({len(error_events)} errors since last alert)"
            body_text, body_html = format_error_alert(error_events)
        else:  # borderline_events only
            alert_type = "borderline"
            subject = (
                f"[DMAF] Borderline Recognitions - Review Needed ({len(borderline_events)} images)"
            )
            body_text, body_html = format_borderline_alert(borderline_events)

        # Send email
        success = self.email_sender.send_email(
            self.config.recipients, subject, body_text, body_html
        )

        if not success:
            logger.error("Failed to send alert email")
            return 0

        # Mark events as alerted
        if borderline_events:
            event_ids = [e["id"] for e in borderline_events]
            self.db.mark_events_alerted(event_ids, "borderline")

        if error_events:
            event_ids = [e["id"] for e in error_events]
            self.db.mark_events_alerted(event_ids, "error")

        # Record alert batch
        for recipient in self.config.recipients:
            self.db.record_alert_sent(alert_type, recipient, total_events)

        logger.info(f"Sent {alert_type} alert with {total_events} event(s)")
        return total_events

    def send_refresh_notification(self, refresh_results: list[dict]) -> bool:
        """
        Send immediate notification for known refresh events.

        Unlike regular alerts, refresh notifications are sent immediately
        (not batched) since they're rare and important.

        Args:
            refresh_results: List of refresh result dicts with keys:
                - person_name: str
                - source_file_path: str
                - target_file_path: str
                - match_score: float
                - target_score: float

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not self.email_sender:
            logger.warning("Email sender not configured, skipping refresh notification")
            return False

        if not refresh_results:
            return False

        count = len(refresh_results)
        subject = f"[DMAF] Known Face Updated - {count} new reference image(s) added"
        body_text, body_html = format_refresh_alert(refresh_results)

        success = self.email_sender.send_email(
            self.config.recipients, subject, body_text, body_html
        )

        if success:
            logger.info(f"Sent refresh notification for {count} image(s)")
        else:
            logger.error("Failed to send refresh notification")

        return success
