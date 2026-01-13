"""Shared pytest fixtures for wa_automate tests."""

import sqlite3
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def known_people_path() -> Path:
    """
    Path to data/known_people/ directory with real test images.

    This fixture is used for integration tests that need real face recognition.
    Returns the absolute path to the known_people directory.
    """
    project_root = Path(__file__).parent.parent
    known_path = project_root / "data" / "known_people"

    if not known_path.exists():
        pytest.skip(f"Known people directory not found: {known_path}")

    return known_path


@pytest.fixture
def unknown_people_path() -> Path:
    """
    Path to data/unknown_people/ directory with stranger test images.

    This fixture is used for realistic FPR testing - most production images
    are of unknown people who should NOT match any known person.
    Returns the absolute path to the unknown_people directory.
    """
    project_root = Path(__file__).parent.parent
    unknown_path = project_root / "data" / "unknown_people"

    if not unknown_path.exists():
        pytest.skip(f"Unknown people directory not found: {unknown_path}")

    return unknown_path


@pytest.fixture
def sample_config_dict() -> dict:
    """Sample configuration dictionary for testing."""
    return {
        "watch_dirs": ["/path/to/whatsapp"],
        "google_photos_album_name": "Test Album",
        "recognition": {
            "backend": "face_recognition",
            "tolerance": 0.52,
            "min_face_size_pixels": 80,
            "require_any_match": True,
            "allow_multiple_people": True,
        },
        "known_people_dir": "./data/known_people",
        "dedup": {
            "method": "sha256",
            "db_path": "./data/state.sqlite3",
        },
        "log_level": "INFO",
    }


@pytest.fixture
def sample_config_yaml(temp_dir: Path, sample_config_dict: dict) -> Path:
    """Create a temporary YAML config file."""
    import yaml

    config_path = temp_dir / "test_config.yaml"

    # Update paths to use temp_dir
    config_dict = sample_config_dict.copy()
    config_dict["watch_dirs"] = [str(temp_dir / "watch")]
    config_dict["known_people_dir"] = str(temp_dir / "known_people")
    config_dict["dedup"]["db_path"] = str(temp_dir / "state.sqlite3")

    # Create required directories
    (temp_dir / "watch").mkdir()
    (temp_dir / "known_people").mkdir()

    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)

    return config_path


@pytest.fixture
def mock_db_path(temp_dir: Path) -> Path:
    """Create a temporary SQLite database path."""
    return temp_dir / "test_state.sqlite3"


@pytest.fixture
def mock_db_connection(mock_db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Create a temporary SQLite database connection."""
    conn = sqlite3.connect(str(mock_db_path))

    # Create the processed_files table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_files (
            file_hash TEXT PRIMARY KEY,
            file_path TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    conn.commit()

    yield conn

    conn.close()


@pytest.fixture
def sample_face_encoding():
    """Sample face encoding (128-dimensional vector for face_recognition backend)."""
    import numpy as np

    return np.random.rand(128).tolist()


@pytest.fixture
def mock_google_photos_service():
    """Mock Google Photos API service."""
    mock_service = MagicMock()

    # Mock mediaItems().batchCreate() response
    mock_service.mediaItems().batchCreate().execute.return_value = {
        "newMediaItemResults": [
            {
                "status": {"message": "Success"},
                "mediaItem": {"id": "mock_item_id", "productUrl": "https://photos.google.com/mock"},
            }
        ]
    }

    # Mock albums().list() response
    mock_service.albums().list().execute.return_value = {
        "albums": [{"id": "mock_album_id", "title": "Test Album"}]
    }

    return mock_service


@pytest.fixture
def mock_face_recognition_model():
    """Mock face_recognition library functions."""
    mock_model = MagicMock()

    # Mock face_locations
    mock_model.face_locations.return_value = [(50, 150, 200, 100)]

    # Mock face_encodings
    import numpy as np

    mock_model.face_encodings.return_value = [np.random.rand(128)]

    # Mock compare_faces
    mock_model.compare_faces.return_value = [True]

    return mock_model


@pytest.fixture
def mock_insightface_model():
    """Mock InsightFace model."""
    mock_model = MagicMock()

    # Mock detection
    mock_face = MagicMock()
    mock_face.bbox = [100, 50, 200, 150]  # [x1, y1, x2, y2]
    import numpy as np

    mock_face.embedding = np.random.rand(512)  # InsightFace uses 512-dim embeddings

    mock_model.get.return_value = [mock_face]

    return mock_model


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration between tests."""
    import logging

    # Store original handlers
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level

    yield

    # Restore original state
    root_logger.handlers = original_handlers
    root_logger.level = original_level
