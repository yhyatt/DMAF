# photos API logic
import json
import pathlib

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from dmaf.utils.retry import RetryConfig, with_retry

SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
    # "https://www.googleapis.com/auth/photoslibrary.readonly",  # albums lookup
    # "https://www.googleapis.com/auth/photoslibrary"  # full control
]


def get_creds(
    token_path: str = "token.json", client_secret_path: str = "client_secret.json"
) -> Credentials:
    creds: Credentials | None = None
    if pathlib.Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        try:
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        except OSError as e:
            import logging
            logging.getLogger(__name__).debug(f"Could not write token file (read-only): {e}")
    return creds


def ensure_album(creds: Credentials, album_name: str | None) -> str | None:
    """Create a new Google Photos album and return its ID.

    NOTE: photoslibrary.appendonly (DMAF's scope) cannot list existing albums —
    that requires photoslibrary.readonly. This function only creates.
    Use get_or_create_album_id to avoid creating duplicates across Cloud Run
    invocations.
    """
    if not album_name:
        return None
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    r = requests.post(
        "https://photoslibrary.googleapis.com/v1/albums",
        headers=headers,
        json={"album": {"title": album_name}},
        timeout=30,
    )
    r.raise_for_status()
    result = r.json().get("id")
    return result if isinstance(result, str) else None


def _firestore_client(project: str):
    """Create a Firestore client (extracted for testability)."""
    from google.cloud import firestore as _fs  # noqa: PLC0415
    return _fs.Client(project=project), _fs.SERVER_TIMESTAMP


def get_or_create_album_id(
    creds: Credentials,
    album_name: str,
    firestore_project: str,
    firestore_collection: str = "dmaf_config",
) -> str | None:
    """Return a cached Google Photos album ID, creating the album only once.

    The album ID is stored in Firestore under
    {firestore_collection}/google_photos_album. On subsequent Cloud Run
    invocations the cached ID is returned immediately — no duplicate albums.

    Root cause this fixes: appendonly scope cannot list albums, so the old
    ensure_album silently failed the GET, then created a new album on every
    job run (once per hour = many duplicate "Family Faces" albums).

    Args:
        creds: Google OAuth credentials (appendonly scope is sufficient).
        album_name: Desired album title.
        firestore_project: GCP project ID for Firestore.
        firestore_collection: Firestore collection for DMAF config docs.

    Returns:
        Album ID string, or None on failure.
    """
    import logging

    logger = logging.getLogger(__name__)
    db, SERVER_TIMESTAMP = _firestore_client(firestore_project)
    ref = db.collection(firestore_collection).document("google_photos_album")

    doc = ref.get()
    if doc.exists:
        data = doc.to_dict() or {}
        cached_id = data.get("album_id")
        cached_name = data.get("album_name")
        if cached_id and cached_name == album_name:
            logger.debug(f"Using cached album ID for '{album_name}': {cached_id[:12]}...")
            return str(cached_id)
        # Album name changed — fall through to create a new one

    album_id = ensure_album(creds, album_name)
    if album_id:
        ref.set({
            "album_name": album_name,
            "album_id": album_id,
            "created_at": SERVER_TIMESTAMP,
        })
        logger.info(f"Created and cached Google Photos album '{album_name}' -> {album_id[:12]}...")
    return album_id


@with_retry(RetryConfig(max_retries=3, base_delay=2.0))
def upload_bytes(creds: Credentials, img_bytes: bytes, filename: str) -> str:
    """Upload raw image bytes to Google Photos."""
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": filename,
        "X-Goog-Upload-Protocol": "raw",
    }
    r = requests.post(
        "https://photoslibrary.googleapis.com/v1/uploads",
        data=img_bytes,
        headers=headers,
        timeout=60,
    )
    r.raise_for_status()
    return r.text  # uploadToken


@with_retry(RetryConfig(max_retries=3, base_delay=2.0))
def create_media_item(
    creds: Credentials, upload_token: str, album_id: str | None, description: str | None = None
):
    """Create a media item in Google Photos from an upload token."""
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    new_item: dict[str, str | dict[str, str]] = {"simpleMediaItem": {"uploadToken": upload_token}}
    if description:
        new_item["description"] = description
    body: dict[str, str | list[dict[str, str | dict[str, str]]]] = {"newMediaItems": [new_item]}
    if album_id:
        body["albumId"] = album_id
    r = requests.post(
        "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate",
        headers=headers,
        data=json.dumps(body),
        timeout=60,
    )
    r.raise_for_status()
    resp = r.json()
    status = resp["newMediaItemResults"][0]["status"]
    if int(status.get("code", 0)) != 0:
        raise RuntimeError(f"Google Photos error: {status}")
    return resp["newMediaItemResults"][0]["mediaItem"]["id"]
