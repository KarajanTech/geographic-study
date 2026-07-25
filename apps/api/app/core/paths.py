"""Repository path discovery.

Local paths are never hardcoded: the repository root is discovered from marker
files so the same code works in a checkout, in a container and in CI.
"""

from __future__ import annotations

from pathlib import Path

# Markers that only exist at the root of the monorepo.
_ROOT_MARKERS = ("docker-compose.yml", ".git")


def find_repo_root(start: Path | None = None) -> Path | None:
    """Return the monorepo root by walking up from ``start``.

    Returns ``None`` when no marker is found, which is the normal situation
    inside a container image that only ships the API package.
    """
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate
    return None


def default_data_dir() -> Path:
    """Directory holding raw, processed and output datasets.

    Falls back to ``<cwd>/data`` when the repository root cannot be found, so a
    misconfigured deployment fails loudly on a missing directory rather than
    writing to an unexpected location.
    """
    root = find_repo_root()
    return (root / "data") if root is not None else (Path.cwd() / "data").resolve()
