#!/usr/bin/env python
"""Download a real DEM into ``data/raw``.

No dataset is bundled with the repository: DEM licensing varies by provider, so
the URL is always supplied by the operator. Suggested public sources are listed
in ``docs/data-sources.md``.

Raw downloads are never overwritten (``--force`` is required) because ingested
datasets are immutable inputs to every analysis run.

Usage:
    uv run --project apps/api python scripts/fetch_dem.py <url> [--out data/raw/dem.tif]
    uv run --project apps/api python scripts/fetch_dem.py <url> --expected-sha256 <hex>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.core.checksum import sha256_file  # noqa: E402 - path set up above

ALLOWED_SCHEMES = {"https", "http", "file"}
DEFAULT_MAX_MB = 2048


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("url", help="Direct URL to a GeoTIFF DEM.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Destination path (default: data/raw/<filename from url>).",
    )
    parser.add_argument(
        "--expected-sha256",
        default=None,
        help="Verify the download against this checksum and delete it on mismatch.",
    )
    parser.add_argument(
        "--max-mb",
        type=int,
        default=DEFAULT_MAX_MB,
        help=f"Size limit (default: {DEFAULT_MAX_MB}).",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    parsed = urlparse(args.url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        print(
            f"Refusing scheme {parsed.scheme!r}; allowed: {sorted(ALLOWED_SCHEMES)}",
            file=sys.stderr,
        )
        return 2

    destination: Path = args.out or (REPO_ROOT / "data" / "raw" / Path(parsed.path).name)
    if not destination.name:
        print("Could not derive a filename from the URL; pass --out.", file=sys.stderr)
        return 2
    if destination.exists() and not args.force:
        print(f"{destination} already exists; pass --force to overwrite.", file=sys.stderr)
        return 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = args.max_mb * 1024 * 1024

    # Download to a temporary file first: a failed transfer must never leave a
    # truncated raster in data/raw.
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False, suffix=".part") as tmp:
        tmp_path = Path(tmp.name)
    try:
        # The URL scheme was validated above before opening it.
        with urllib.request.urlopen(args.url) as response, tmp_path.open("wb") as handle:
            written = 0
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    msg = f"Download exceeds --max-mb ({args.max_mb} MB)"
                    raise RuntimeError(msg)
                handle.write(chunk)

        checksum = sha256_file(tmp_path)
        if args.expected_sha256 and checksum != args.expected_sha256:
            msg = f"Checksum mismatch: expected {args.expected_sha256}, got {checksum}"
            raise RuntimeError(msg)

        shutil.move(str(tmp_path), destination)
    except Exception as error:  # noqa: BLE001 - report and clean up whatever failed
        tmp_path.unlink(missing_ok=True)
        print(f"Download failed: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "checksum_sha256": checksum,
                "source": args.url,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
