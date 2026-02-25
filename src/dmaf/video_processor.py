"""
Video processing for face recognition.

Extracts frames from video files and runs face recognition,
stopping as soon as a known face is found.
"""

import logging
from pathlib import Path

import cv2
import numpy as np

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
    """Get the MIME type for a video file based on its extension."""
    return VIDEO_MIME_TYPES.get(Path(path).suffix.lower(), "video/mp4")


def extract_frames(video_path: Path, fps: float = 1.0) -> list[tuple[float, np.ndarray]]:
    """
    Extract frames from a video at the given fps rate.
    For clips shorter than 10s, uses 2fps instead.

    Returns list of (timestamp_seconds, frame_rgb_array).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.warning(f"Cannot open video: {video_path}")
        return []

    try:
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if video_fps <= 0:
            logger.warning(f"Invalid FPS for {video_path}")
            return []

        duration = total_frames / video_fps

        # For short clips (<10s), sample at 2fps
        sample_fps = 2.0 if duration < 10.0 else fps

        frame_interval = max(1, int(video_fps / sample_fps))
        frames: list[tuple[float, np.ndarray]] = []
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                timestamp = frame_idx / video_fps
                # Convert BGR to RGB
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append((timestamp, rgb_frame))

            frame_idx += 1

        return frames
    finally:
        cap.release()


def find_face_in_video(
    video_path: Path,
    process_fn,
) -> tuple[bool, list[str], float | None, float | None]:
    """
    Scan video frames for known faces. Stops on first match.

    Args:
        video_path: Path to the video file
        process_fn: Callable that takes np_img and returns
                    (matched, who, scores) or (matched, who)

    Returns:
        (matched, who, best_score, match_timestamp_seconds)
    """
    try:
        frames = extract_frames(video_path)
    except Exception as e:
        logger.warning(f"Failed to extract frames from {video_path}: {e}")
        return (False, [], None, None)

    if not frames:
        logger.warning(f"No frames extracted from {video_path}")
        return (False, [], None, None)

    for timestamp, frame in frames:
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
                return (True, who, best_score, timestamp)
        except Exception as e:
            logger.warning(f"Error processing frame at {timestamp:.1f}s: {e}")
            continue

    return (False, [], None, None)
