"""Local object storage layout.

Raw uploads live under ``data/raw`` and are treated as immutable: derived
products are always written to ``data/processed`` or ``data/outputs``.
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from app.core.checksum import sha256_file
from app.core.config import Settings, get_settings
from app.core.errors import InvalidInputError

_PROBE_NAME = ".sentinel-write-probe"
_CHUNK_BYTES = 1024 * 1024

# GeoTIFF only for now. Extensions are checked because GDAL drivers are chosen
# by content, and an unexpected driver is an unexpected attack surface.
ALLOWED_RASTER_SUFFIXES = frozenset({".tif", ".tiff"})
ALLOWED_RASTER_CONTENT_TYPES = frozenset(
    {
        "image/tiff",
        "image/geotiff",
        "application/octet-stream",
        "application/x-geotiff",
        "",
    }
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_data_dirs(settings: Settings | None = None) -> tuple[Path, Path, Path]:
    """Create the raw/processed/outputs directories if they do not exist."""
    cfg = settings or get_settings()
    for directory in (cfg.raw_dir, cfg.processed_dir, cfg.outputs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return cfg.raw_dir, cfg.processed_dir, cfg.outputs_dir


def check_data_dir_writable(settings: Settings | None = None) -> bool:
    """Return ``True`` when the data directory exists and accepts writes."""
    cfg = settings or get_settings()
    probe = cfg.data_dir / _PROBE_NAME
    try:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return False
    return True


def resolve_within(root: Path, *parts: str) -> Path:
    """Join ``parts`` under ``root`` and refuse anything that escapes it.

    Guards against path traversal coming from user supplied names.
    """
    root = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    if candidate != root and root not in candidate.parents:
        msg = "Resolved path escapes its storage root"
        raise InvalidInputError(msg, details={"root": str(root), "candidate": str(candidate)})
    return candidate


# --- Dataset layout ----------------------------------------------------------


def safe_filename(name: str) -> str:
    """Reduce an uploaded filename to something safe to put on disk.

    Only the basename survives, and only characters that cannot form a path.
    """
    stem = Path(name).name
    cleaned = _SAFE_NAME.sub("_", stem).strip("._-")
    return cleaned or "upload"


def raw_dataset_dir(project_id: uuid.UUID, dataset_id: uuid.UUID, settings: Settings) -> Path:
    """Directory holding the untouched upload for a dataset."""
    return resolve_within(settings.raw_dir, "projects", str(project_id), str(dataset_id))


def processed_dataset_dir(project_id: uuid.UUID, dataset_id: uuid.UUID, settings: Settings) -> Path:
    """Directory holding everything derived from a raw dataset."""
    return resolve_within(settings.processed_dir, "projects", str(project_id), str(dataset_id))


def to_relative_uri(path: Path, settings: Settings) -> str:
    """Store paths relative to the data directory, never absolute.

    The same row must resolve on a laptop and inside a container.
    """
    return str(path.resolve().relative_to(settings.data_dir))


def from_relative_uri(uri: str, settings: Settings) -> Path:
    """Resolve a stored relative URI back to an absolute path."""
    return resolve_within(settings.data_dir, *Path(uri).parts)


# --- Uploads -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredUpload:
    path: Path
    size_bytes: int
    checksum_sha256: str


def validate_raster_upload(filename: str, content_type: str | None) -> None:
    """Reject anything that is not a GeoTIFF before a byte is written."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_RASTER_SUFFIXES:
        msg = f"Unsupported file type {suffix or '(none)'}; upload a GeoTIFF (.tif or .tiff)"
        raise InvalidInputError(
            msg, details={"filename": filename, "allowed": sorted(ALLOWED_RASTER_SUFFIXES)}
        )
    normalised = (content_type or "").split(";")[0].strip().lower()
    if normalised not in ALLOWED_RASTER_CONTENT_TYPES:
        msg = f"Unsupported content type {content_type!r}; expected a GeoTIFF"
        raise InvalidInputError(msg, details={"content_type": content_type})


def store_upload(source: BinaryIO, destination: Path, *, max_bytes: int) -> StoredUpload:
    """Write an upload to ``destination``, enforcing the size limit as it streams.

    The bytes land in a temporary file first, so a rejected or interrupted
    upload never leaves a partial dataset in ``data/raw``. Raw files are written
    once and never modified afterwards.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        msg = "Refusing to overwrite an existing raw dataset"
        raise InvalidInputError(msg, details={"path": destination.name})

    with NamedTemporaryFile(dir=destination.parent, delete=False, suffix=".part") as handle:
        temp_path = Path(handle.name)
        written = 0
        try:
            while chunk := source.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    msg = f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit"
                    raise InvalidInputError(msg, details={"max_bytes": max_bytes})
                handle.write(chunk)
        except Exception:
            handle.close()
            temp_path.unlink(missing_ok=True)
            raise

    if written == 0:
        temp_path.unlink(missing_ok=True)
        msg = "Uploaded file is empty"
        raise InvalidInputError(msg)

    shutil.move(str(temp_path), destination)
    # Raw data is immutable: make that explicit on the filesystem too.
    destination.chmod(0o444)
    return StoredUpload(
        path=destination, size_bytes=written, checksum_sha256=sha256_file(destination)
    )
