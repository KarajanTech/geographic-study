#!/usr/bin/env python
"""Generate the synthetic sample DEM used by the local demo and by tests.

The output is synthetic terrain, not a survey of a real place. Use
``scripts/fetch_dem.py`` to bring in a real DEM.

Usage:
    uv run --project apps/api python scripts/make_sample_dem.py
    uv run --project apps/api python scripts/make_sample_dem.py --out data/raw/dem.tif --width 800
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.geo.sample_dem import (  # noqa: E402 - path set up above
    DEFAULT_SAMPLE_CRS,
    SyntheticDemSpec,
    write_synthetic_dem,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data" / "raw" / "sample_dem_synthetic.tif",
        help="Destination GeoTIFF (default: data/raw/sample_dem_synthetic.tif).",
    )
    parser.add_argument("--width", type=int, default=400, help="Columns (default: 400).")
    parser.add_argument("--height", type=int, default=400, help="Rows (default: 400).")
    parser.add_argument(
        "--resolution", type=float, default=25.0, help="Cell size in metres (default: 25)."
    )
    parser.add_argument(
        "--crs",
        default=DEFAULT_SAMPLE_CRS,
        help=f"Projected metric CRS (default: {DEFAULT_SAMPLE_CRS}).",
    )
    parser.add_argument(
        "--seed", type=int, default=20240101, help="Random seed (default: 20240101)."
    )
    parser.add_argument("--force", action="store_true", help="Overwrite the destination file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.out.exists() and not args.force:
        print(f"{args.out} already exists; pass --force to overwrite.", file=sys.stderr)
        return 1

    spec = SyntheticDemSpec(
        width=args.width,
        height=args.height,
        resolution_m=args.resolution,
        crs=args.crs,
        seed=args.seed,
    )
    result = write_synthetic_dem(args.out, spec)

    print(
        json.dumps(
            {
                "path": str(result.path),
                "crs": result.crs,
                "bounds_m": result.bounds,
                "resolution_m": result.resolution_m,
                "nodata": result.nodata,
                "units": result.units,
                "checksum_sha256": result.checksum_sha256,
                "elevation_range_m": [result.min_elevation_m, result.max_elevation_m],
                "source": "synthetic",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
