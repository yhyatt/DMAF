"""
Video processing for face recognition.

Streams frames from video files and runs face recognition,
stopping as soon as a known face is found.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# cv2 and numpy are optional heavy dependencies — imported lazily inside
# functions so that the module can be imported even when they are not installed
# (e.g. in lightweight test environments that skip face-recognition tests).

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".3gp", ".mkv", ".webm"}

VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".3gp": "video/3gpp",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


def is_video_file(path: str | Path) -> bool:
    """Check if a file path has a video extension."""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def get_video_mime_type(path: str | Path) -> str:
    """
    Get the MIME type for a video file based on its extension.

    Note:
        Not used by the Google Photos upload flow, which sends raw bytes
        without a content-type header. Kept here for documentation and
        potential future use if MIME-type-specific behaviour is needed.
    """
    return VIDEO_MIME_TYPES.get(Path(path).suffix.lower(), "video/mp4")


def iter_frames(
    video_path: Path, fps: float = 1.0
) -> Generator[tuple[float, np.ndarray], None, None]:
    """
    Yield frames from a video one at a time (generator).

    For clips shorter than 10s, samples at 2fps instead of the given fps.
    Yields (timestamp_seconds, frame_rgb_array) and releases the capture
    handle when the caller stops consuming or the video ends.

    Using a generator means find_face_in_video can stop extraction the
    moment a match is found — no wasted memory or CPU on remaining frames.
    """
    try:
        import cv2
        import numpy as np  # noqa: F401 — needed for type annotation at runtime
    except ImportError as e:
        raise ImportError(
            "opencv-python-headless is required for video processing. "
            "Install with: pip install dmaf[insightface]"
        ) from e

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning(f"Cannot open video: {video_path}")
        return

    try:
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if video_fps <= 0:
            logger.warning(f"Invalid FPS for {video_path}")
            return

        duration = total_frames / video_fps
        sample_fps = 2.0 if duration < 10.0 else fps
        frame_interval = max(1, int(video_fps / sample_fps))
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % frame_interval == 0:
                timestamp = frame_idx / video_fps
                yield timestamp, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_idx += 1
    finally:
        cap.release()


def extract_frames(video_path: Path, fps: float = 1.0) -> list[tuple[float, np.ndarray]]:
    """
    Extract all sampled frames into a list.

    Convenience wrapper around iter_frames for callers (e.g. tests) that
    need the full frame list upfront. Production code should prefer
    iter_frames directly to benefit from early-exit memory savings.
    """
    return list(iter_frames(video_path, fps))


def find_face_in_video(
    video_path: Path,
    process_fn,
) -> tuple[bool, list[str], float | None, float | None]:
    """
    Scan video frames for known faces. Stops on first match.

    Frames are streamed one at a time via iter_frames — when a match is
    found the generator is abandoned immediately, so no further frames
    are decoded or held in memory.

    Args:
        video_path: Path to the video file.
        process_fn: Callable (np_img) -> (matched, who, scores) or
                    (matched, who).

    Returns:
        (matched, who, best_score, match_timestamp_seconds)
    """
    try:
        frame_gen = iter_frames(video_path)
    except Exception as e:
        logger.warning(f"Failed to open video {video_path}: {e}")
        return (False, [], None, None)

    for timestamp, frame in frame_gen:
        try:
            result = process_fn(frame)
            if len(result) == 3:
                matched, who, scores = result
            else:
                matched, who = result
                scores = {}

            if matched:
                best_score = max(scores.values()) if scores else None
                logger.info(
                    f"Face match in video {video_path.name} at {timestamp:.1f}s -> {who}"
                )
                frame_gen.close()  # stop the generator, release cap immediately
                return (True, who, best_score, timestamp)
        except Exception as e:
            logger.warning(f"Error processing frame at {timestamp:.1f}s: {e}")
            continue

    return (False, [], None, None)
