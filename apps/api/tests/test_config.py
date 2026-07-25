"""Configuration is environment driven and never hardcoded to a machine."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings, get_settings
from app.core.paths import default_data_dir, find_repo_root


def test_defaults_are_local_and_absolute() -> None:
    settings = Settings()

    assert settings.environment is Environment.LOCAL
    assert settings.data_dir.is_absolute()
    assert settings.raw_dir == settings.data_dir / "raw"
    assert settings.processed_dir == settings.data_dir / "processed"
    assert settings.outputs_dir == settings.data_dir / "outputs"


def test_environment_overrides_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_DATA_DIR", str(tmp_path / "elsewhere"))

    settings = Settings()

    assert settings.data_dir == (tmp_path / "elsewhere").resolve()


def test_cors_origins_accepts_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_CORS_ORIGINS", "http://a.test, http://b.test")

    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="chatty")


def test_log_level_is_normalised_to_upper_case() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"


@pytest.mark.parametrize(
    ("environment", "override", "expected"),
    [
        (Environment.LOCAL, None, False),
        (Environment.PRODUCTION, None, True),
        (Environment.LOCAL, True, True),
        (Environment.PRODUCTION, False, False),
    ],
)
def test_json_logging_defaults_per_environment(
    environment: Environment, override: bool | None, expected: bool
) -> None:
    settings = Settings(environment=environment, log_json=override)

    assert settings.use_json_logs is expected


def test_upload_limit_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(max_upload_mb=0)

    assert Settings(max_upload_mb=2).max_upload_bytes == 2 * 1024 * 1024


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.api_port = 1234  # type: ignore[misc]


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_repo_root_is_discovered_from_markers() -> None:
    root = find_repo_root()

    assert root is not None
    assert (root / "docker-compose.yml").exists() or (root / ".git").exists()
    assert default_data_dir() == root / "data"


def test_repo_root_returns_none_outside_a_checkout(tmp_path: Path) -> None:
    assert find_repo_root(tmp_path) is None
