"""Storage layout and path isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import InvalidInputError
from app.services.storage import check_data_dir_writable, ensure_data_dirs, resolve_within


def test_ensure_data_dirs_creates_the_three_roots(settings: Settings) -> None:
    raw, processed, outputs = ensure_data_dirs(settings)

    assert raw.is_dir()
    assert processed.is_dir()
    assert outputs.is_dir()


def test_ensure_data_dirs_is_idempotent(settings: Settings) -> None:
    ensure_data_dirs(settings)
    marker = settings.raw_dir / "dem.tif"
    marker.write_bytes(b"raw-bytes")

    ensure_data_dirs(settings)

    assert marker.read_bytes() == b"raw-bytes"


def test_writable_check_detects_a_read_only_directory(settings: Settings) -> None:
    assert check_data_dir_writable(settings) is True

    settings.data_dir.chmod(0o500)
    try:
        assert check_data_dir_writable(settings) is False
    finally:
        settings.data_dir.chmod(0o700)


def test_resolve_within_allows_nested_paths(tmp_path: Path) -> None:
    resolved = resolve_within(tmp_path, "project-1", "dem.tif")

    assert resolved == (tmp_path / "project-1" / "dem.tif").resolve()


@pytest.mark.parametrize("evil", ["../escape.tif", "a/../../escape.tif", "/etc/passwd"])
def test_resolve_within_rejects_traversal(tmp_path: Path, evil: str) -> None:
    with pytest.raises(InvalidInputError):
        resolve_within(tmp_path, evil)
