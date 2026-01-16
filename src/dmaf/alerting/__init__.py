"""
Email alerting system for DMAF.

Provides batched email notifications for:
- Processing and upload errors
- Borderline recognition scores (near misses)
- Known face refresh events
"""

from dmaf.alerting.alert_manager import AlertManager
from dmaf.alerting.email_sender import EmailSender

__all__ = ["AlertManager", "EmailSender"]
