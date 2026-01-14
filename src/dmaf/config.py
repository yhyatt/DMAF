"""
Configuration management using Pydantic for validation.

Supports loading from:
- YAML files (primary)
- Environment variables with WA_AUTOMATE_ prefix
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RecognitionSettings(BaseModel):
    """Face recognition configuration."""

    backend: Literal["face_recognition", "insightface"] = Field(
        default="face_recognition",
        description="Face recognition backend to use",
    )
    tolerance: float = Field(
        default=0.52,
        ge=0.0,
        le=1.0,
        description="Matching threshold (lower = stricter). "
        "Typical: 0.5-0.6 for face_recognition, 0.3-0.5 for insightface",
    )
    min_face_size_pixels: int = Field(
        default=80,
        ge=20,
        description="Minimum face size in pixels to detect",
    )
    require_any_match: bool = Field(
        default=True,
        description="Require at least one recognized face to upload",
    )
    allow_multiple_people: bool = Field(
        default=True,
        description="Upload if any of the whitelisted people appear",
    )


class DedupSettings(BaseModel):
    """Deduplication configuration."""

    method: Literal["sha256"] = Field(
        default="sha256",
        description="Hash method for deduplication",
    )
    backend: Literal["sqlite", "firestore"] = Field(
        default="sqlite",
        description="Database backend: 'sqlite' (local) or 'firestore' (cloud)",
    )

    # SQLite settings (used when backend="sqlite")
    db_path: Path = Field(
        default=Path("./state.sqlite3"),
        description="Path to SQLite database for tracking processed files",
    )

    # Firestore settings (used when backend="firestore")
    firestore_project: str | None = Field(
        default=None,
        description="GCP project ID for Firestore (required when backend=firestore)",
    )
    firestore_collection: str = Field(
        default="dmaf_files",
        description="Firestore collection name",
    )

    @field_validator("db_path", mode="before")
    @classmethod
    def parse_db_path(cls, v):
        """Convert string path to Path object."""
        if isinstance(v, str):
            return Path(v)
        return v

    @model_validator(mode="after")
    def validate_backend_config(self):
        """Validate that required fields are set for the chosen backend."""
        if self.backend == "firestore" and not self.firestore_project:
            raise ValueError("firestore_project is required when dedup.backend='firestore'")
        return self


class Settings(BaseSettings):
    """
    Main application settings.

    Can be loaded from:
    - YAML file: Settings.from_yaml("config.yaml")
    - Environment variables: WA_AUTOMATE_LOG_LEVEL=DEBUG
    """

    model_config = SettingsConfigDict(
        env_prefix="WA_AUTOMATE_",
        env_nested_delimiter="__",
        extra="ignore",  # Ignore unknown fields for forward compatibility
    )

    watch_dirs: list[Path] = Field(
        default_factory=list,
        description="Directories to watch for new images",
    )
    google_photos_album_name: str | None = Field(
        default=None,
        description="Optional album name to upload images to",
    )
    known_people_dir: Path = Field(
        default=Path("./known_people"),
        description="Directory containing known face images",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    recognition: RecognitionSettings = Field(
        default_factory=RecognitionSettings,
        description="Face recognition settings",
    )
    dedup: DedupSettings = Field(
        default_factory=DedupSettings,
        description="Deduplication settings",
    )

    @field_validator("watch_dirs", mode="before")
    @classmethod
    def parse_watch_dirs(cls, v):
        """Convert string paths to Path objects."""
        if isinstance(v, list):
            return [Path(p) if isinstance(p, str) else p for p in v]
        return v

    @field_validator("known_people_dir", mode="before")
    @classmethod
    def parse_known_people_dir(cls, v):
        """Convert string path to Path object."""
        if isinstance(v, str):
            return Path(v)
        return v

    @model_validator(mode="after")
    def validate_paths(self) -> "Settings":
        """Validate that required paths exist or can be created."""
        # known_people_dir should exist
        if not self.known_people_dir.exists():
            raise ValueError(f"known_people_dir does not exist: {self.known_people_dir}")
        return self

    @classmethod
    def from_yaml(cls, path: Path | str) -> "Settings":
        """
        Load settings from a YAML file.

        Args:
            path: Path to YAML configuration file

        Returns:
            Settings instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save settings to a YAML file."""
        path = Path(path)

        # Convert to dict, handling Path objects
        data = self.model_dump()

        def convert_paths(obj):
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [convert_paths(item) for item in obj]
            return obj

        data = convert_paths(data)

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
