"""Content checksums.

Every dataset is identified by the checksum of its bytes: it is the anchor of
provenance and of the viewshed cache key.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, read in chunks so large rasters fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
