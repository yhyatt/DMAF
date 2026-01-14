"""Tests for Google Photos API integration."""

from unittest.mock import Mock, mock_open, patch

import pytest

from dmaf.google_photos.api import (
    SCOPES,
    create_media_item,
    ensure_album,
    get_creds,
    upload_bytes,
)


class TestGetCreds:
    """Test OAuth credential management."""

    @patch("pathlib.Path.exists")
    @patch("dmaf.google_photos.api.Credentials")
    def test_load_existing_valid_creds(self, mock_creds_class, mock_exists):
        """Test loading existing valid credentials."""
        mock_exists.return_value = True

        # Mock valid credentials
        mock_creds = Mock()
        mock_creds.valid = True
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        creds = get_creds("token.json", "client_secret.json")

        assert creds == mock_creds
        mock_creds_class.from_authorized_user_file.assert_called_once_with("token.json", SCOPES)

    @patch("pathlib.Path.exists")
    @patch("dmaf.google_photos.api.Credentials")
    @patch("builtins.open", new_callable=mock_open)
    def test_refresh_expired_creds(self, mock_file, mock_creds_class, mock_exists):
        """Test refreshing expired credentials."""
        mock_exists.return_value = True

        # Mock expired credentials with refresh token
        mock_creds = Mock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token_123"
        mock_creds.to_json.return_value = '{"token": "new_token"}'
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        creds = get_creds("token.json", "client_secret.json")

        # Should have called refresh
        mock_creds.refresh.assert_called_once()

        # Should have saved refreshed token
        mock_file.assert_called_once_with("token.json", "w")
        mock_file().write.assert_called_once_with('{"token": "new_token"}')

        assert creds == mock_creds

    @patch("pathlib.Path.exists")
    @patch("dmaf.google_photos.api.Credentials")
    @patch("dmaf.google_photos.api.InstalledAppFlow")
    @patch("builtins.open", new_callable=mock_open)
    def test_new_auth_flow(self, mock_file, mock_flow_class, mock_creds_class, mock_exists):
        """Test running new OAuth flow when no valid credentials exist."""
        mock_exists.return_value = False

        # Mock new credentials from OAuth flow
        mock_creds = Mock()
        mock_creds.to_json.return_value = '{"token": "fresh_token"}'

        mock_flow = Mock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_class.from_client_secrets_file.return_value = mock_flow

        creds = get_creds("token.json", "client_secret.json")

        # Should have created flow and run local server
        mock_flow_class.from_client_secrets_file.assert_called_once_with(
            "client_secret.json", SCOPES
        )
        mock_flow.run_local_server.assert_called_once_with(port=0)

        # Should have saved new token
        mock_file.assert_called_once_with("token.json", "w")
        mock_file().write.assert_called_once_with('{"token": "fresh_token"}')

        assert creds == mock_creds

    @patch("pathlib.Path.exists")
    @patch("dmaf.google_photos.api.Credentials")
    @patch("dmaf.google_photos.api.InstalledAppFlow")
    @patch("builtins.open", new_callable=mock_open)
    def test_invalid_creds_no_refresh_token(
        self, mock_file, mock_flow_class, mock_creds_class, mock_exists
    ):
        """Test OAuth flow when credentials are invalid and have no refresh token."""
        mock_exists.return_value = True

        # Mock invalid credentials without refresh token
        old_creds = Mock()
        old_creds.valid = False
        old_creds.expired = True
        old_creds.refresh_token = None
        mock_creds_class.from_authorized_user_file.return_value = old_creds

        # Mock new credentials from OAuth flow
        new_creds = Mock()
        new_creds.to_json.return_value = '{"token": "new_token"}'

        mock_flow = Mock()
        mock_flow.run_local_server.return_value = new_creds
        mock_flow_class.from_client_secrets_file.return_value = mock_flow

        creds = get_creds("token.json", "client_secret.json")

        # Should have run OAuth flow (not refresh)
        mock_flow_class.from_client_secrets_file.assert_called_once()
        old_creds.refresh.assert_not_called()

        assert creds == new_creds


class TestEnsureAlbum:
    """Test album lookup and creation."""

    def test_none_album_name(self):
        """Test that None album_name returns None."""
        mock_creds = Mock()
        result = ensure_album(mock_creds, None)
        assert result is None

    @patch("dmaf.google_photos.api.requests.get")
    def test_find_existing_album(self, mock_get):
        """Test finding an existing album by name."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        # Mock API response with existing album
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "albums": [
                {"id": "album_1", "title": "Other Album"},
                {"id": "album_2", "title": "My Test Album"},
                {"id": "album_3", "title": "Another Album"},
            ]
        }
        mock_get.return_value = mock_response

        album_id = ensure_album(mock_creds, "My Test Album")

        assert album_id == "album_2"
        mock_get.assert_called_once()

    @patch("dmaf.google_photos.api.requests.get")
    @patch("dmaf.google_photos.api.requests.post")
    def test_create_new_album(self, mock_post, mock_get):
        """Test creating a new album when it doesn't exist."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        # Mock GET response (album not found)
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {"albums": []}
        mock_get.return_value = mock_get_response

        # Mock POST response (album created)
        mock_post_response = Mock()
        mock_post_response.json.return_value = {"id": "new_album_id"}
        mock_post.return_value = mock_post_response

        album_id = ensure_album(mock_creds, "New Album")

        assert album_id == "new_album_id"

        # Verify POST was called with correct data
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"] == {"album": {"title": "New Album"}}

    @patch("dmaf.google_photos.api.requests.get")
    @patch("dmaf.google_photos.api.requests.post")
    def test_api_error_no_albums_returned(self, mock_post, mock_get):
        """Test handling API response without albums key."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        # Mock API response without albums
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {}
        mock_get.return_value = mock_get_response

        # Mock album creation
        mock_post_response = Mock()
        mock_post_response.json.return_value = {"id": "created_album_id"}
        mock_post.return_value = mock_post_response

        # Should proceed to create album when not found
        album_id = ensure_album(mock_creds, "Album")
        assert album_id == "created_album_id"


class TestUploadBytes:
    """Test image upload to Google Photos."""

    @patch("dmaf.google_photos.api.requests.post")
    def test_successful_upload(self, mock_post):
        """Test successful image upload."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        # Mock successful upload response
        mock_response = Mock()
        mock_response.text = "upload_token_abc123"
        mock_post.return_value = mock_response

        image_bytes = b"fake_image_data"
        token = upload_bytes(mock_creds, image_bytes, "test.jpg")

        assert token == "upload_token_abc123"

        # Verify POST was called correctly
        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args

        assert call_args[0] == "https://photoslibrary.googleapis.com/v1/uploads"
        assert call_kwargs["data"] == image_bytes
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["X-Goog-Upload-File-Name"] == "test.jpg"

    @patch("dmaf.google_photos.api.requests.post")
    def test_upload_with_retry_decorator(self, mock_post):
        """Test that upload has retry logic on network errors."""
        import requests

        mock_creds = Mock()
        mock_creds.token = "test_token"

        # First call raises RequestException (retryable), second succeeds
        mock_response_success = Mock()
        mock_response_success.text = "token_after_retry"

        mock_post.side_effect = [requests.ConnectionError("Network error"), mock_response_success]

        # Due to @with_retry decorator, this should succeed after retry
        with patch("dmaf.utils.retry.time.sleep"):  # Mock sleep to speed up test
            token = upload_bytes(mock_creds, b"data", "test.jpg")

            assert token == "token_after_retry"
            assert mock_post.call_count == 2


class TestCreateMediaItem:
    """Test media item creation in Google Photos."""

    @patch("dmaf.google_photos.api.requests.post")
    def test_create_without_album(self, mock_post):
        """Test creating media item without album."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        # Mock successful creation response
        mock_response = Mock()
        mock_response.json.return_value = {
            "newMediaItemResults": [{"status": {"code": 0}, "mediaItem": {"id": "media_item_123"}}]
        }
        mock_post.return_value = mock_response

        item_id = create_media_item(mock_creds, "upload_token", None)

        assert item_id == "media_item_123"

        # Verify POST body
        call_kwargs = mock_post.call_args[1]
        import json

        body = json.loads(call_kwargs["data"])

        assert "newMediaItems" in body
        assert body["newMediaItems"][0]["simpleMediaItem"]["uploadToken"] == "upload_token"
        assert "albumId" not in body

    @patch("dmaf.google_photos.api.requests.post")
    def test_create_with_album(self, mock_post):
        """Test creating media item with album."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        mock_response = Mock()
        mock_response.json.return_value = {
            "newMediaItemResults": [{"status": {"code": 0}, "mediaItem": {"id": "media_item_456"}}]
        }
        mock_post.return_value = mock_response

        item_id = create_media_item(mock_creds, "upload_token", "album_id_789")

        assert item_id == "media_item_456"

        # Verify albumId was included
        call_kwargs = mock_post.call_args[1]
        import json

        body = json.loads(call_kwargs["data"])
        assert body["albumId"] == "album_id_789"

    @patch("dmaf.google_photos.api.requests.post")
    def test_create_with_description(self, mock_post):
        """Test creating media item with description."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        mock_response = Mock()
        mock_response.json.return_value = {
            "newMediaItemResults": [{"status": {"code": 0}, "mediaItem": {"id": "media_item_789"}}]
        }
        mock_post.return_value = mock_response

        item_id = create_media_item(
            mock_creds, "upload_token", None, description="Test photo description"
        )

        assert item_id == "media_item_789"

        # Verify description was included
        call_kwargs = mock_post.call_args[1]
        import json

        body = json.loads(call_kwargs["data"])
        assert body["newMediaItems"][0]["description"] == "Test photo description"

    @patch("dmaf.google_photos.api.requests.post")
    def test_create_with_error_status(self, mock_post):
        """Test handling Google Photos API error status."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        # Mock error response from Google Photos
        mock_response = Mock()
        mock_response.json.return_value = {
            "newMediaItemResults": [{"status": {"code": 3, "message": "Invalid upload token"}}]
        }
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="Google Photos error"):
            create_media_item(mock_creds, "invalid_token", None)

    @patch("dmaf.google_photos.api.requests.post")
    def test_create_with_retry_decorator(self, mock_post):
        """Test that create_media_item has retry logic."""
        mock_creds = Mock()
        mock_creds.token = "test_token"

        # First call fails with retryable error, second succeeds
        import requests

        mock_error_response = Mock()
        mock_error_response.status_code = 503
        mock_error_response.raise_for_status.side_effect = requests.HTTPError(
            response=mock_error_response
        )

        mock_success_response = Mock()
        mock_success_response.json.return_value = {
            "newMediaItemResults": [
                {"status": {"code": 0}, "mediaItem": {"id": "item_after_retry"}}
            ]
        }

        mock_post.side_effect = [mock_error_response, mock_success_response]

        with patch("dmaf.utils.retry.time.sleep"):
            item_id = create_media_item(mock_creds, "token", None)

            assert item_id == "item_after_retry"
            assert mock_post.call_count == 2


class TestGooglePhotosIntegration:
    """Test integration between Google Photos functions."""

    @patch("dmaf.google_photos.api.requests.post")
    @patch("dmaf.google_photos.api.requests.get")
    @patch("pathlib.Path.exists")
    @patch("dmaf.google_photos.api.Credentials")
    def test_full_upload_workflow(self, mock_creds_class, mock_exists, mock_get, mock_post):
        """Test complete workflow: auth -> upload -> create item."""
        # Setup: Mock valid credentials
        mock_exists.return_value = True
        mock_creds = Mock()
        mock_creds.valid = True
        mock_creds.token = "test_token"
        mock_creds_class.from_authorized_user_file.return_value = mock_creds

        # Step 1: Get credentials
        creds = get_creds()
        assert creds.valid

        # Step 2: Mock upload_bytes
        mock_upload_response = Mock()
        mock_upload_response.text = "upload_token_xyz"
        mock_post.return_value = mock_upload_response

        upload_token = upload_bytes(creds, b"image_data", "photo.jpg")
        assert upload_token == "upload_token_xyz"

        # Step 3: Mock create_media_item
        mock_create_response = Mock()
        mock_create_response.json.return_value = {
            "newMediaItemResults": [{"status": {"code": 0}, "mediaItem": {"id": "final_item_id"}}]
        }
        mock_post.return_value = mock_create_response

        item_id = create_media_item(creds, upload_token, None)
        assert item_id == "final_item_id"
