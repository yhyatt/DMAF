"""
Face recognition backends.

Provides a unified interface to multiple face recognition libraries:
- face_recognition (dlib-based, CPU-optimized)
- insightface (deep learning, more accurate)
"""

from dmaf.face_recognition.factory import best_match, load_known_faces

__all__ = [
    "load_known_faces",
    "best_match",
]
