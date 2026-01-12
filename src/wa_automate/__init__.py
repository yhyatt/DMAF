"""
wa_automate - Automated WhatsApp media backup with face recognition filtering.

This package monitors WhatsApp media directories, identifies photos containing
known faces, and automatically uploads them to Google Photos.
"""

__version__ = "0.1.0"
__author__ = "Yonatan"

from wa_automate.config import Settings
from wa_automate.database import Database, get_conn

__all__ = [
    "__version__",
    "Settings",
    "Database",
    "get_conn",
]
