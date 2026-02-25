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

    backend: Literal["face_recognition", "insightface", "auraface"] = Field(
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
    det_thresh: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description=(
            "InsightFace detection confidence threshold for test images "
            "(lower = more faces detected). "
            "0.4 = balanced (catches difficult angles), "
            "0.5 = strict (obvious faces only), "
            "0.35 = permissive (may detect non-faces). "
            "Ignored for face_recognition backend."
        ),
    )
    det_thresh_known: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="InsightFace detection threshold for known_people images (training set). "
        "Lower than det_thresh because we assume faces exist in training images. "
        "0.3 = permissive (detect even difficult angles), 0.4 = balanced. "
        "Ignored for face_recognition backend.",
    )
    return_best_only: bool = Field(
        default=True,
        description="Use only highest confidence face per image when multiple faces detected. "
        "Recommended for known_people with group photos to avoid encoding background faces. "
        "Applies to both known face loading and test image matching (insightface only).",
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


class KnownRefreshSettings(BaseModel):
    """Known people auto-refresh configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable automatic refresh of known_people images",
    )
    interval_days: int = Field(
        default=60,  # ~2 months
        ge=7,
        description="Days between refresh checks (minimum 7)",
    )
    target_score: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Target match score for refresh images. "
        "Images closest to this score are selected. "
        "0.65 = moderate confidence (not too easy, not too hard)",
    )
    crop_padding_percent: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Padding around face bounding box when cropping (0.3 = 30%)",
    )


class SmtpSettings(BaseModel):
    """SMTP configuration for email alerts."""

    host: str = Field(
        description="SMTP server hostname (e.g., smtp.gmail.com)",
    )
    port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port (587 for TLS, 465 for SSL)",
    )
    username: str = Field(
        description="SMTP authentication username",
    )
    password: str = Field(
        description="SMTP authentication password (use app-specific password)",
    )
    use_tls: bool = Field(
        default=True,
        description="Use STARTTLS encryption",
    )
    sender_email: str = Field(
        description="From address for alert emails",
    )


class AlertSettings(BaseModel):
    """Alert configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable email alerting",
    )
    recipients: list[str] = Field(
        default_factory=list,
        description="Email addresses to send alerts to",
    )
    batch_interval_minutes: int = Field(
        default=60,
        ge=1,
        description="Minimum interval between alert emails (to prevent spam)",
    )
    borderline_offset: float = Field(
        default=0.1,
        ge=0.0,
        le=0.5,
        description="Score range below tolerance to flag as borderline. "
        "E.g., 0.1 means scores in [tolerance-0.1, tolerance] are borderline.",
    )
    event_retention_days: int = Field(
        default=90,
        ge=7,
        description="Delete alerted events older than this many days",
    )
    smtp: SmtpSettings | None = Field(
        default=None,
        description="SMTP settings (required when enabled=True)",
    )

    @model_validator(mode="after")
    def validate_smtp_required(self):
        """Validate SMTP is configured when alerts are enabled."""
        if self.enabled and self.smtp is None:
            raise ValueError("SMTP settings required when alerting is enabled")
        if self.enabled and not self.recipients:
            raise ValueError("At least one recipient required when alerting is enabled")
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

    watch_dirs: list[Path | str] = Field(
        default_factory=list,
        description="Directories to watch for new images. Supports local paths and GCS URIs (gs://bucket/prefix).",
    )
    google_photos_album_name: str | None = Field(
        default=None,
        description="Optional album name to upload images to",
    )
    known_people_dir: Path = Field(
        default=Path("./known_people"),
        description="Directory containing known face images",
    )
    known_people_gcs_uri: str | None = Field(
        default=None,
        description=(
            "GCS URI for known_people reference images (e.g. gs://bucket/prefix). "
            "Downloaded to known_people_dir at container startup."
        ),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    delete_source_after_upload: bool = Field(
        default=False,
        description="Delete source image after successful Google Photos upload. "
        "Useful for cloud staging (Dropbox) to prevent storage bloat. "
        "WARNING: Destructive - files are permanently deleted!",
    )
    delete_unmatched_after_processing: bool = Field(
        default=False,
        description="Delete images that don't match any known faces after processing. "
        "WARNING: VERY DESTRUCTIVE - use only for pure staging directories where "
        "ALL photos are expected to contain known faces. "
        "Personal photos without known faces will be permanently deleted!",
    )
    recognition: RecognitionSettings = Field(
        default_factory=RecognitionSettings,
        description="Face recognition settings",
    )
    dedup: DedupSettings = Field(
        default_factory=DedupSettings,
        description="Deduplication settings",
    )
    known_refresh: KnownRefreshSettings = Field(
        default_factory=KnownRefreshSettings,
        description="Known people auto-refresh settings",
    )
    alerting: AlertSettings = Field(
        default_factory=AlertSettings,
        description="Email alerting settings",
    )

    @field_validator("watch_dirs", mode="before")
    @classmethod
    def parse_watch_dirs(cls, v):
        """Convert string paths to Path objects, preserving GCS URIs as strings."""
        if isinstance(v, list):
            result = []
            for p in v:
                if isinstance(p, str) and p.startswith("gs://"):
                    result.append(p)  # Keep GCS URIs as strings — Path() strips the double slash
                elif isinstance(p, str):
                    result.append(Path(p))
                else:
                    result.append(p)
            return result
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
        if not self.known_people_dir.exists():
            if self.known_people_gcs_uri:
                # Will be populated at startup from GCS
                self.known_people_dir.mkdir(parents=True, exist_ok=True)
            else:
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
