"""
Google Photos API integration.

Provides OAuth authentication and media upload functionality.
"""

from dmaf.google_photos.api import (
    SCOPES,
    create_media_item,
    ensure_album,
    get_creds,
    upload_bytes,
)

__all__ = [
    "get_creds",
    "ensure_album",
    "upload_bytes",
    "create_media_item",
    "SCOPES",
]
