"""
GCS watch source for DMAF.

Enables using Google Cloud Storage buckets as watch directories.
Usage in config: watch_dirs: ["gs://my-bucket/prefix/"]

Requires: pip install dmaf[gcs]
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def _get_storage_client():
    """Get a GCS client, raising a clear error if not installed."""
    try:
        from google.cloud import storage
    except ImportError as e:
        raise ImportError(
            "google-cloud-storage is required for GCS watch directories. "
            "Install with: pip install dmaf[gcs]"
        ) from e
    return storage.Client()


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    """
    Parse a gs:// URI into (bucket_name, prefix).

    Args:
        uri: GCS URI like 'gs://bucket/prefix/' or 'gs://bucket'

    Returns:
        (bucket_name, prefix) where prefix may be empty string

    Raises:
        ValueError: If the URI is not a valid GCS URI with scheme 'gs' and a non-empty bucket.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "gs":
        raise ValueError(f"Invalid GCS URI '{uri}': scheme must be 'gs'")
    bucket = parsed.netloc
    if not bucket:
        raise ValueError(f"Invalid GCS URI '{uri}': bucket name is missing")
    prefix = parsed.path.lstrip("/")
    return bucket, prefix


def list_gcs_images(uri: str) -> list[str]:
    """
    List all image files in a GCS bucket/prefix.

    Args:
        uri: GCS URI like 'gs://bucket/prefix/'

    Returns:
        List of full GCS paths like 'gs://bucket/path/to/image.jpg'
    """
    client = _get_storage_client()
    bucket_name, prefix = parse_gcs_uri(uri)
    bucket = client.bucket(bucket_name)

    gcs_paths = []
    for blob in bucket.list_blobs(prefix=prefix):
        # Skip "directory" markers
        if blob.name.endswith("/"):
            continue
        suffix = Path(blob.name).suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            gcs_paths.append(f"gs://{bucket_name}/{blob.name}")
    return gcs_paths


def download_gcs_blob(gcs_path: str) -> Path:
    """
    Download a GCS blob to a temporary file.

    Args:
        gcs_path: Full GCS path like 'gs://bucket/path/to/image.jpg'

    Returns:
        Path to the downloaded temporary file. Caller must clean up with cleanup_temp_file().
    """
    client = _get_storage_client()
    bucket_name, blob_name = parse_gcs_uri(gcs_path)
    # blob_name from parse_gcs_uri is the prefix, but for a full path it's the object key
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    suffix = Path(blob_name).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="dmaf_gcs_")
    tmp.close()
    blob.download_to_filename(tmp.name)

    logger.debug(f"Downloaded {gcs_path} -> {tmp.name}")
    return Path(tmp.name)


def cleanup_temp_file(local_path: Path) -> None:
    """
    Remove a temporary file created by download_gcs_blob.

    Args:
        local_path: Path to temporary file
    """
    try:
        local_path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"Failed to clean up temp file {local_path}: {e}")


def is_gcs_uri(path: str) -> bool:
    """Check if a path is a GCS URI."""
    return path.startswith("gs://")
