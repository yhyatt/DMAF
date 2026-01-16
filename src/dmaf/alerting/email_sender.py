"""
Email sending functionality using SMTP.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dmaf.config import SmtpSettings

logger = logging.getLogger(__name__)


class EmailSender:
    """Handles SMTP email sending with TLS."""

    def __init__(self, smtp_config: SmtpSettings):
        """
        Initialize email sender.

        Args:
            smtp_config: SMTP configuration settings
        """
        self.config = smtp_config

    def send_email(
        self,
        recipients: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> bool:
        """
        Send an email via SMTP.

        Args:
            recipients: List of recipient email addresses
            subject: Email subject line
            body_text: Plain text email body
            body_html: Optional HTML email body

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not recipients:
            logger.warning("No recipients specified, skipping email")
            return False

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["From"] = self.config.sender_email
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject

            # Attach plain text body
            msg.attach(MIMEText(body_text, "plain"))

            # Attach HTML body if provided
            if body_html:
                msg.attach(MIMEText(body_html, "html"))

            # Connect to SMTP server
            if self.config.use_tls:
                with smtplib.SMTP(self.config.host, self.config.port) as server:
                    server.starttls()
                    server.login(self.config.username, self.config.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.config.host, self.config.port) as server:
                    server.login(self.config.username, self.config.password)
                    server.send_message(msg)

            logger.info(f"Email sent successfully to {len(recipients)} recipient(s)")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
