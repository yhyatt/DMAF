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
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def ensure_album(creds: Credentials, album_name: str | None) -> str | None:
    if not album_name:
        return None
    # Needs photoslibrary.readonly or photoslibrary scope to list-create albums.
    # Safer approach: create once manually and paste album ID here.
    # Example call below requires elevated scopes - comment out if using appendonly-only.
    headers = {"Authorization": f"Bearer {creds.token}"}
    # Try to find existing album
    r = requests.get(
        "https://photoslibrary.googleapis.com/v1/albums?pageSize=50", headers=headers, timeout=30
    )
    if r.status_code == 200:
        albums_list = r.json().get("albums", [])
        for album in albums_list:
            if album.get("title") == album_name:
                album_id = album.get("id")
                return album_id if isinstance(album_id, str) else None
    # Create album
    body_dict = {"album": {"title": album_name}}
    r = requests.post(
        "https://photoslibrary.googleapis.com/v1/albums",
        headers=headers,
        json=body_dict,
        timeout=30,
    )
    r.raise_for_status()
    result = r.json().get("id")
    return result if isinstance(result, str) else None


@with_retry(RetryConfig(max_retries=3, base_delay=2.0))
def upload_bytes(creds: Credentials, img_bytes: bytes, filename: str) -> str:
    """
    Upload raw image bytes to Google Photos.

    Automatically retries on network errors and 429/5xx HTTP errors.

    Args:
        creds: Google OAuth credentials
        img_bytes: Image data as bytes
        filename: Original filename (for metadata)

    Returns:
        Upload token to use with create_media_item
    """
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
    """
    Create a media item in Google Photos from an upload token.

    Automatically retries on network errors and 429/5xx HTTP errors.

    Args:
        creds: Google OAuth credentials
        upload_token: Token from upload_bytes()
        album_id: Optional album ID to add the item to
        description: Optional description for the media item

    Returns:
        Media item ID

    Raises:
        RuntimeError: If Google Photos API returns an error status
    """
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
