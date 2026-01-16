"""Tests for configuration management."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from dmaf.config import DedupSettings, RecognitionSettings, Settings


class TestRecognitionSettings:
    """Test RecognitionSettings validation."""

    def test_default_values(self):
        """Test default recognition settings."""
        settings = RecognitionSettings()
        assert settings.backend == "face_recognition"
        assert settings.tolerance == 0.52
        assert settings.min_face_size_pixels == 80
        assert settings.require_any_match is True
        assert settings.allow_multiple_people is True

    def test_valid_backends(self):
        """Test valid backend choices."""
        for backend in ["face_recognition", "insightface"]:
            settings = RecognitionSettings(backend=backend)
            assert settings.backend == backend

    def test_invalid_backend(self):
        """Test that invalid backend raises validation error."""
        with pytest.raises(ValidationError, match="Input should be"):
            RecognitionSettings(backend="invalid_backend")

    def test_tolerance_bounds(self):
        """Test tolerance must be between 0 and 1."""
        # Valid values
        RecognitionSettings(tolerance=0.0)
        RecognitionSettings(tolerance=0.5)
        RecognitionSettings(tolerance=1.0)

        # Invalid values
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            RecognitionSettings(tolerance=-0.1)

        with pytest.raises(ValidationError, match="less than or equal to 1"):
            RecognitionSettings(tolerance=1.1)

    def test_min_face_size_bounds(self):
        """Test min_face_size_pixels must be >= 20."""
        RecognitionSettings(min_face_size_pixels=20)
        RecognitionSettings(min_face_size_pixels=100)

        with pytest.raises(ValidationError, match="greater than or equal to 20"):
            RecognitionSettings(min_face_size_pixels=10)


class TestDedupSettings:
    """Test DedupSettings validation."""

    def test_default_values(self):
        """Test default deduplication settings."""
        settings = DedupSettings()
        assert settings.method == "sha256"
        assert settings.db_path == Path("./state.sqlite3")

    def test_path_conversion(self):
        """Test string paths are converted to Path objects."""
        settings = DedupSettings(db_path="/custom/path.sqlite3")
        assert isinstance(settings.db_path, Path)
        assert settings.db_path == Path("/custom/path.sqlite3")

    def test_path_object_preserved(self):
        """Test Path objects are preserved."""
        path = Path("/custom/path.sqlite3")
        settings = DedupSettings(db_path=path)
        assert settings.db_path == path


class TestSettings:
    """Test main Settings validation."""

    def test_default_values(self):
        """Test default settings with minimal required data."""
        # Create a temporary known_people directory to satisfy validation
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            known_dir = Path(tmpdir) / "known_people"
            known_dir.mkdir()

            settings = Settings(known_people_dir=known_dir)
            assert settings.watch_dirs == []
            assert settings.google_photos_album_name is None
            assert settings.known_people_dir == known_dir
            assert settings.log_level == "INFO"
            assert isinstance(settings.recognition, RecognitionSettings)
            assert isinstance(settings.dedup, DedupSettings)

    def test_watch_dirs_conversion(self):
        """Test watch_dirs string paths are converted to Path objects."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            known_dir = Path(tmpdir) / "known_people"
            known_dir.mkdir()

            settings = Settings(
                watch_dirs=["/path/1", "/path/2"],
                known_people_dir=known_dir,
            )
            assert all(isinstance(p, Path) for p in settings.watch_dirs)
            assert settings.watch_dirs == [Path("/path/1"), Path("/path/2")]

    def test_known_people_dir_must_exist(self):
        """Test that known_people_dir must exist."""
        with pytest.raises(ValidationError, match="known_people_dir does not exist"):
            Settings(known_people_dir="/nonexistent/path")

    def test_valid_log_levels(self):
        """Test valid log level choices."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            known_dir = Path(tmpdir) / "known_people"
            known_dir.mkdir()

            for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                settings = Settings(log_level=level, known_people_dir=known_dir)
                assert settings.log_level == level

    def test_invalid_log_level(self):
        """Test that invalid log level raises validation error."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            known_dir = Path(tmpdir) / "known_people"
            known_dir.mkdir()

            with pytest.raises(ValidationError, match="Input should be"):
                Settings(log_level="INVALID", known_people_dir=known_dir)

    def test_nested_settings(self):
        """Test nested recognition and dedup settings."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            known_dir = Path(tmpdir) / "known_people"
            known_dir.mkdir()

            settings = Settings(
                known_people_dir=known_dir,
                recognition={"backend": "insightface", "tolerance": 0.45},
                dedup={"method": "sha256", "db_path": "/custom/db.sqlite3"},
            )
            assert settings.recognition.backend == "insightface"
            assert settings.recognition.tolerance == 0.45
            assert settings.dedup.db_path == Path("/custom/db.sqlite3")


class TestSettingsYAML:
    """Test YAML loading and saving."""

    def test_from_yaml_success(self, sample_config_yaml: Path):
        """Test successful YAML loading."""
        settings = Settings.from_yaml(sample_config_yaml)
        assert len(settings.watch_dirs) > 0
        assert isinstance(settings.recognition, RecognitionSettings)
        assert isinstance(settings.dedup, DedupSettings)

    def test_from_yaml_file_not_found(self):
        """Test loading from nonexistent YAML file."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            Settings.from_yaml("/nonexistent/config.yaml")

    def test_from_yaml_empty_file(self, temp_dir: Path):
        """Test loading from empty YAML file (should use defaults)."""
        empty_yaml = temp_dir / "empty.yaml"
        empty_yaml.write_text("")

        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        # Empty YAML should fail because known_people_dir doesn't exist at default path
        with pytest.raises(ValidationError, match="known_people_dir does not exist"):
            Settings.from_yaml(empty_yaml)

    def test_from_yaml_invalid_tolerance(self, temp_dir: Path):
        """Test that invalid tolerance in YAML raises error."""
        import yaml

        invalid_yaml = temp_dir / "invalid.yaml"
        data = {
            "recognition": {"tolerance": 2.0},  # Invalid: > 1.0
            "known_people_dir": str(temp_dir / "known_people"),
        }

        # Create known_people_dir
        (temp_dir / "known_people").mkdir()

        with open(invalid_yaml, "w") as f:
            yaml.dump(data, f)

        with pytest.raises(ValidationError, match="less than or equal to 1"):
            Settings.from_yaml(invalid_yaml)

    def test_to_yaml(self, temp_dir: Path, sample_config_dict: dict):
        """Test saving settings to YAML."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        # Create settings
        settings = Settings(
            watch_dirs=[temp_dir / "watch"],
            known_people_dir=known_dir,
            google_photos_album_name="Test Album",
            log_level="DEBUG",
        )

        # Save to YAML
        output_path = temp_dir / "output.yaml"
        settings.to_yaml(output_path)

        assert output_path.exists()

        # Load it back and verify
        loaded = Settings.from_yaml(output_path)
        assert loaded.log_level == "DEBUG"
        assert loaded.google_photos_album_name == "Test Album"
        assert loaded.known_people_dir == known_dir

    def test_yaml_roundtrip(self, sample_config_yaml: Path, temp_dir: Path):
        """Test that loading and saving YAML preserves data."""
        # Load original
        original = Settings.from_yaml(sample_config_yaml)

        # Save to new file
        output_path = temp_dir / "roundtrip.yaml"
        original.to_yaml(output_path)

        # Load the saved file
        reloaded = Settings.from_yaml(output_path)

        # Compare key fields
        assert reloaded.log_level == original.log_level
        assert reloaded.recognition.backend == original.recognition.backend
        assert reloaded.recognition.tolerance == original.recognition.tolerance
        assert reloaded.dedup.method == original.dedup.method


class TestEnvironmentVariables:
    """Test environment variable loading."""

    def test_env_var_override(self, temp_dir: Path, monkeypatch):
        """Test that environment variables override defaults."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        # Set environment variables
        monkeypatch.setenv("WA_AUTOMATE_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("WA_AUTOMATE_GOOGLE_PHOTOS_ALBUM_NAME", "EnvAlbum")

        settings = Settings(known_people_dir=known_dir)
        assert settings.log_level == "DEBUG"
        assert settings.google_photos_album_name == "EnvAlbum"

    def test_nested_env_var(self, temp_dir: Path, monkeypatch):
        """Test nested environment variables with double underscore."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        monkeypatch.setenv("WA_AUTOMATE_RECOGNITION__BACKEND", "insightface")
        monkeypatch.setenv("WA_AUTOMATE_RECOGNITION__TOLERANCE", "0.45")

        settings = Settings(known_people_dir=known_dir)
        assert settings.recognition.backend == "insightface"
        assert settings.recognition.tolerance == 0.45

    def test_env_var_extra_ignored(self, temp_dir: Path, monkeypatch):
        """Test that unknown environment variables are ignored."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        # Set an unknown environment variable
        monkeypatch.setenv("WA_AUTOMATE_UNKNOWN_FIELD", "value")

        # Should not raise error due to extra="ignore"
        settings = Settings(known_people_dir=known_dir)
        assert not hasattr(settings, "unknown_field")


class TestSettingsValidation:
    """Test Settings model validators."""

    def test_watch_dirs_empty_list(self, temp_dir: Path):
        """Test that watch_dirs can be an empty list."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        settings = Settings(watch_dirs=[], known_people_dir=known_dir)
        assert settings.watch_dirs == []

    def test_google_photos_album_name_null(self, temp_dir: Path):
        """Test that google_photos_album_name can be None."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        settings = Settings(google_photos_album_name=None, known_people_dir=known_dir)
        assert settings.google_photos_album_name is None


class TestKnownRefreshSettings:
    """Test KnownRefreshSettings configuration."""

    def test_default_values(self):
        """Test default values for refresh settings."""
        from dmaf.config import KnownRefreshSettings

        settings = KnownRefreshSettings()

        assert settings.enabled is False
        assert settings.interval_days == 60
        assert settings.target_score == 0.65
        assert settings.crop_padding_percent == 0.3

    def test_valid_interval_days(self):
        """Test valid interval_days values."""
        from dmaf.config import KnownRefreshSettings

        settings = KnownRefreshSettings(interval_days=7)
        assert settings.interval_days == 7

        settings = KnownRefreshSettings(interval_days=365)
        assert settings.interval_days == 365

    def test_invalid_interval_days_too_low(self):
        """Test that interval_days must be >= 7."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import KnownRefreshSettings

        with pytest.raises(ValidationError) as exc_info:
            KnownRefreshSettings(interval_days=6)

        assert "interval_days" in str(exc_info.value)

    def test_valid_target_score(self):
        """Test valid target_score range."""
        from dmaf.config import KnownRefreshSettings

        settings = KnownRefreshSettings(target_score=0.0)
        assert settings.target_score == 0.0

        settings = KnownRefreshSettings(target_score=0.5)
        assert settings.target_score == 0.5

        settings = KnownRefreshSettings(target_score=1.0)
        assert settings.target_score == 1.0

    def test_invalid_target_score_out_of_range(self):
        """Test that target_score must be 0-1."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import KnownRefreshSettings

        with pytest.raises(ValidationError):
            KnownRefreshSettings(target_score=-0.1)

        with pytest.raises(ValidationError):
            KnownRefreshSettings(target_score=1.1)

    def test_valid_crop_padding(self):
        """Test valid crop_padding_percent range."""
        from dmaf.config import KnownRefreshSettings

        settings = KnownRefreshSettings(crop_padding_percent=0.0)
        assert settings.crop_padding_percent == 0.0

        settings = KnownRefreshSettings(crop_padding_percent=0.5)
        assert settings.crop_padding_percent == 0.5

        settings = KnownRefreshSettings(crop_padding_percent=1.0)
        assert settings.crop_padding_percent == 1.0

    def test_invalid_crop_padding_out_of_range(self):
        """Test that crop_padding_percent must be 0-1."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import KnownRefreshSettings

        with pytest.raises(ValidationError):
            KnownRefreshSettings(crop_padding_percent=-0.1)

        with pytest.raises(ValidationError):
            KnownRefreshSettings(crop_padding_percent=1.1)


class TestSmtpSettings:
    """Test SmtpSettings configuration."""

    def test_valid_smtp_config(self):
        """Test valid SMTP configuration."""
        from dmaf.config import SmtpSettings

        settings = SmtpSettings(
            host="smtp.gmail.com",
            port=587,
            username="user@example.com",
            password="app-password",
            use_tls=True,
            sender_email="alerts@example.com",
        )

        assert settings.host == "smtp.gmail.com"
        assert settings.port == 587
        assert settings.username == "user@example.com"
        assert settings.password == "app-password"
        assert settings.use_tls is True
        assert settings.sender_email == "alerts@example.com"

    def test_default_port_and_tls(self):
        """Test default values for port and TLS."""
        from dmaf.config import SmtpSettings

        settings = SmtpSettings(
            host="smtp.example.com",
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )

        assert settings.port == 587
        assert settings.use_tls is True

    def test_valid_port_range(self):
        """Test valid port range."""
        from dmaf.config import SmtpSettings

        settings = SmtpSettings(
            host="smtp.example.com",
            port=25,
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )
        assert settings.port == 25

        settings = SmtpSettings(
            host="smtp.example.com",
            port=465,
            username="user",
            password="pass",
            sender_email="sender@example.com",
        )
        assert settings.port == 465

    def test_invalid_port_out_of_range(self):
        """Test that port must be 1-65535."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import SmtpSettings

        with pytest.raises(ValidationError):
            SmtpSettings(
                host="smtp.example.com",
                port=0,
                username="user",
                password="pass",
                sender_email="sender@example.com",
            )

        with pytest.raises(ValidationError):
            SmtpSettings(
                host="smtp.example.com",
                port=65536,
                username="user",
                password="pass",
                sender_email="sender@example.com",
            )


class TestAlertSettings:
    """Test AlertSettings configuration."""

    def test_default_values(self):
        """Test default values for alert settings."""
        from dmaf.config import AlertSettings

        settings = AlertSettings()

        assert settings.enabled is False
        assert settings.recipients == []
        assert settings.batch_interval_minutes == 60
        assert settings.borderline_offset == 0.1
        assert settings.event_retention_days == 90
        assert settings.smtp is None

    def test_valid_alert_config(self):
        """Test valid alert configuration."""
        from dmaf.config import AlertSettings, SmtpSettings

        smtp = SmtpSettings(
            host="smtp.gmail.com",
            username="user@example.com",
            password="pass",
            sender_email="alerts@example.com",
        )

        settings = AlertSettings(enabled=True, recipients=["user@example.com"], smtp=smtp)

        assert settings.enabled is True
        assert settings.recipients == ["user@example.com"]
        assert settings.smtp is not None

    def test_valid_batch_interval(self):
        """Test valid batch_interval_minutes."""
        from dmaf.config import AlertSettings

        settings = AlertSettings(batch_interval_minutes=30)
        assert settings.batch_interval_minutes == 30

        settings = AlertSettings(batch_interval_minutes=1440)  # 24 hours
        assert settings.batch_interval_minutes == 1440

    def test_invalid_batch_interval_too_low(self):
        """Test that batch_interval_minutes must be >= 1."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import AlertSettings

        with pytest.raises(ValidationError):
            AlertSettings(batch_interval_minutes=0)

    def test_valid_borderline_offset(self):
        """Test valid borderline_offset range."""
        from dmaf.config import AlertSettings

        settings = AlertSettings(borderline_offset=0.0)
        assert settings.borderline_offset == 0.0

        settings = AlertSettings(borderline_offset=0.25)
        assert settings.borderline_offset == 0.25

        settings = AlertSettings(borderline_offset=0.5)
        assert settings.borderline_offset == 0.5

    def test_invalid_borderline_offset_out_of_range(self):
        """Test that borderline_offset must be 0-0.5."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import AlertSettings

        with pytest.raises(ValidationError):
            AlertSettings(borderline_offset=-0.1)

        with pytest.raises(ValidationError):
            AlertSettings(borderline_offset=0.6)

    def test_valid_retention_days(self):
        """Test valid event_retention_days."""
        from dmaf.config import AlertSettings

        settings = AlertSettings(event_retention_days=7)
        assert settings.event_retention_days == 7

        settings = AlertSettings(event_retention_days=365)
        assert settings.event_retention_days == 365

    def test_invalid_retention_days_too_low(self):
        """Test that event_retention_days must be >= 7."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import AlertSettings

        with pytest.raises(ValidationError):
            AlertSettings(event_retention_days=6)

    def test_validate_smtp_required_when_enabled(self):
        """Test that SMTP is required when alerting is enabled."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import AlertSettings

        with pytest.raises(ValidationError) as exc_info:
            AlertSettings(enabled=True, recipients=["user@example.com"], smtp=None)

        assert "SMTP settings required" in str(exc_info.value)

    def test_validate_recipients_required_when_enabled(self):
        """Test that recipients are required when alerting is enabled."""
        import pytest
        from pydantic import ValidationError

        from dmaf.config import AlertSettings, SmtpSettings

        smtp = SmtpSettings(
            host="smtp.gmail.com",
            username="user@example.com",
            password="pass",
            sender_email="alerts@example.com",
        )

        with pytest.raises(ValidationError) as exc_info:
            AlertSettings(enabled=True, recipients=[], smtp=smtp)

        assert "At least one recipient required" in str(exc_info.value)

    def test_alerting_disabled_no_smtp_required(self):
        """Test that SMTP is not required when alerting is disabled."""
        from dmaf.config import AlertSettings

        # Should not raise error
        settings = AlertSettings(enabled=False, recipients=[], smtp=None)
        assert settings.enabled is False


class TestSettingsWithNewFields:
    """Test Settings model with new fields."""

    def test_settings_has_known_refresh(self, temp_dir: Path):
        """Test that Settings includes known_refresh field."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        settings = Settings(known_people_dir=known_dir)

        assert hasattr(settings, "known_refresh")
        assert settings.known_refresh.enabled is False

    def test_settings_has_alerting(self, temp_dir: Path):
        """Test that Settings includes alerting field."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        settings = Settings(known_people_dir=known_dir)

        assert hasattr(settings, "alerting")
        assert settings.alerting.enabled is False

    def test_settings_with_refresh_enabled(self, temp_dir: Path):
        """Test Settings with refresh enabled."""
        from dmaf.config import KnownRefreshSettings

        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        refresh_settings = KnownRefreshSettings(enabled=True, interval_days=30)
        settings = Settings(known_people_dir=known_dir, known_refresh=refresh_settings)

        assert settings.known_refresh.enabled is True
        assert settings.known_refresh.interval_days == 30

    def test_settings_with_alerting_enabled(self, temp_dir: Path):
        """Test Settings with alerting enabled."""
        from dmaf.config import AlertSettings, SmtpSettings

        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        smtp = SmtpSettings(
            host="smtp.gmail.com",
            username="user@example.com",
            password="pass",
            sender_email="alerts@example.com",
        )
        alerting_settings = AlertSettings(enabled=True, recipients=["user@example.com"], smtp=smtp)

        settings = Settings(known_people_dir=known_dir, alerting=alerting_settings)

        assert settings.alerting.enabled is True
        assert len(settings.alerting.recipients) == 1

    def test_settings_yaml_with_new_fields(self, temp_dir: Path):
        """Test loading Settings from YAML with new fields."""
        known_dir = temp_dir / "known_people"
        known_dir.mkdir()

        yaml_content = f"""
watch_dirs:
  - /test/dir

known_people_dir: {known_dir}

recognition:
  backend: face_recognition
  tolerance: 0.52

known_refresh:
  enabled: true
  interval_days: 30
  target_score: 0.70

alerting:
  enabled: true
  recipients:
    - user@example.com
  batch_interval_minutes: 120
  smtp:
    host: smtp.gmail.com
    port: 587
    username: alerts@example.com
    password: secret
    sender_email: alerts@example.com
"""

        yaml_path = temp_dir / "config.yaml"
        yaml_path.write_text(yaml_content)

        settings = Settings.from_yaml(yaml_path)

        # Verify refresh settings
        assert settings.known_refresh.enabled is True
        assert settings.known_refresh.interval_days == 30
        assert settings.known_refresh.target_score == 0.70

        # Verify alerting settings
        assert settings.alerting.enabled is True
        assert settings.alerting.recipients == ["user@example.com"]
        assert settings.alerting.batch_interval_minutes == 120
        assert settings.alerting.smtp.host == "smtp.gmail.com"
