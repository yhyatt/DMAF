"""Tests for video_processor module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

cv2 = pytest.importorskip("cv2", reason="cv2 not installed (requires dmaf[insightface])")
import numpy as np  # noqa: E402 — after importorskip guard

from dmaf.video_processor import (
    VIDEO_EXTENSIONS,
    extract_frames,
    find_face_in_video,
    get_video_mime_type,
    is_video_file,
)


def _make_test_video(duration_s: float = 5.0, fps: float = 10.0) -> Path:
    """Create a small synthetic video file for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    path = Path(tmp.name)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (64, 64))

    total_frames = int(duration_s * fps)
    for i in range(total_frames):
        frame = np.full((64, 64, 3), fill_value=i % 256, dtype=np.uint8)
        writer.write(frame)

    writer.release()
    return path


class TestIsVideoFile:
    def test_video_extensions(self):
        for ext in [".mp4", ".mov", ".avi", ".3gp", ".mkv", ".webm"]:
            assert is_video_file(f"test{ext}") is True

    def test_non_video_extensions(self):
        for ext in [".jpg", ".png", ".txt", ".pdf", ".heic"]:
            assert is_video_file(f"test{ext}") is False

    def test_case_insensitive(self):
        assert is_video_file("test.MP4") is True
        assert is_video_file("test.MoV") is True

    def test_path_object(self):
        assert is_video_file(Path("/some/dir/clip.mp4")) is True


class TestGetVideoMimeType:
    def test_known_types(self):
        assert get_video_mime_type("a.mp4") == "video/mp4"
        assert get_video_mime_type("a.mov") == "video/quicktime"

    def test_unknown_defaults_mp4(self):
        assert get_video_mime_type("a.xyz") == "video/mp4"


class TestExtractFrames:
    def test_frame_count_1fps(self):
        path = _make_test_video(duration_s=15.0, fps=10.0)
        try:
            frames = extract_frames(path, fps=1.0)
            # 15s video at 1fps → ~15 frames (may vary by ±1 due to rounding)
            assert 14 <= len(frames) <= 16
        finally:
            path.unlink()

    def test_short_clip_uses_2fps(self):
        path = _make_test_video(duration_s=5.0, fps=10.0)
        try:
            frames = extract_frames(path, fps=1.0)
            # 5s clip (<10s) → 2fps → ~10 frames
            assert 9 <= len(frames) <= 11
        finally:
            path.unlink()

    def test_frames_are_rgb(self):
        path = _make_test_video(duration_s=2.0, fps=5.0)
        try:
            frames = extract_frames(path, fps=1.0)
            assert len(frames) > 0
            ts, frame = frames[0]
            assert frame.ndim == 3
            assert frame.shape[2] == 3  # RGB
            assert isinstance(ts, float)
        finally:
            path.unlink()

    def test_corrupt_video_returns_empty(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp.write(b"not a video")
        tmp.close()
        try:
            frames = extract_frames(Path(tmp.name))
            assert frames == []
        finally:
            Path(tmp.name).unlink()


class TestFindFaceInVideo:
    def test_match_on_second_frame_early_exit(self):
        path = _make_test_video(duration_s=15.0, fps=10.0)
        call_count = 0

        def mock_process(np_img):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return (True, ["Zoe"], {"Zoe": 0.85})
            return (False, [], {})

        try:
            matched, who, score, ts = find_face_in_video(path, mock_process)
            assert matched is True
            assert who == ["Zoe"]
            assert score == 0.85
            assert ts is not None
            assert call_count == 2  # Early exit
        finally:
            path.unlink()

    def test_no_match(self):
        path = _make_test_video(duration_s=3.0, fps=5.0)

        def mock_process(np_img):
            return (False, [], {})

        try:
            matched, who, score, ts = find_face_in_video(path, mock_process)
            assert matched is False
            assert who == []
            assert score is None
            assert ts is None
        finally:
            path.unlink()

    def test_old_format_process_fn(self):
        """Test backward compat with (matched, who) return format."""
        path = _make_test_video(duration_s=3.0, fps=5.0)

        def mock_process(np_img):
            return (True, ["Lenny"])

        try:
            matched, who, score, ts = find_face_in_video(path, mock_process)
            assert matched is True
            assert who == ["Lenny"]
            assert score is None  # No scores in old format
        finally:
            path.unlink()

    def test_corrupt_video(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp.write(b"garbage data")
        tmp.close()
        try:
            matched, who, score, ts = find_face_in_video(
                Path(tmp.name), lambda x: (False, [], {})
            )
            assert matched is False
            assert who == []
        finally:
            Path(tmp.name).unlink()


class TestListGcsVideos:
    def test_filters_video_extensions(self):
        def make_blob(name):
            return MagicMock(name=name, **{"name": name})

        blobs = [
            make_blob("prefix/clip.mp4"),
            make_blob("prefix/photo.jpg"),
            make_blob("prefix/movie.mov"),
            make_blob("prefix/doc.txt"),
            make_blob("prefix/short.3gp"),
            make_blob("prefix/"),
        ]

        with patch("dmaf.gcs_watcher._get_storage_client") as mock_client:
            mock_bucket = MagicMock()
            mock_bucket.list_blobs.return_value = blobs
            mock_client.return_value.bucket.return_value = mock_bucket

            from dmaf.gcs_watcher import list_gcs_videos

            result = list_gcs_videos("gs://test-bucket/prefix/")

            assert "gs://test-bucket/prefix/clip.mp4" in result
            assert "gs://test-bucket/prefix/movie.mov" in result
            assert "gs://test-bucket/prefix/short.3gp" in result
            assert len(result) == 3
