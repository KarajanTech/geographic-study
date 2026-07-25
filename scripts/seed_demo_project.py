#!/usr/bin/env python
"""Create a demonstration project, ingest a DEM, generate candidates, and
queue viewshed computation for them.

This exists so the Phase 1, 2 and 3 pipelines can be run end to end without a
frontend form (that arrives in Phase 5). It talks to the API over HTTP,
exactly as a client would. Viewsheds are only *queued*: a worker
(`make dev-worker`, or the `worker` Compose service) must be running to
actually compute them.

By default it generates synthetic terrain and a study area over it, both
clearly marked as synthetic. Pass ``--dem`` to ingest a real GeoTIFF instead.

Usage:
    uv run --project apps/api python scripts/seed_demo_project.py
    uv run --project apps/api python scripts/seed_demo_project.py --dem data/raw/mdt25.tif
    uv run --project apps/api python scripts/seed_demo_project.py --api-url http://localhost:8000
    uv run --project apps/api python scripts/seed_demo_project.py --spacing-m 200 --max-slope-deg 15
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

# httpx2 ships with the dev dependencies; this is a development-time script.
import httpx2  # noqa: E402 - path set up above
import rasterio  # noqa: E402
from shapely.geometry import box, mapping  # noqa: E402

from app.geo.area import reproject_geometry  # noqa: E402
from app.geo.sample_dem import SyntheticDemSpec, write_synthetic_dem  # noqa: E402

DEFAULT_API_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Base URL of the API.")
    parser.add_argument("--name", default="Demo — synthetic terrain", help="Project name.")
    parser.add_argument(
        "--dem",
        type=Path,
        default=None,
        help="GeoTIFF to ingest. A synthetic DEM is generated when omitted.",
    )
    parser.add_argument(
        "--buffer-m",
        type=float,
        default=2_000.0,
        help="Clip buffer in metres (default: 2000).",
    )
    parser.add_argument(
        "--inset",
        type=float,
        default=0.25,
        help="Fraction of the DEM inset on each side to form the study area (default: 0.25).",
    )
    parser.add_argument(
        "--spacing-m",
        type=float,
        default=200.0,
        help="Candidate grid spacing, metres (default: 200).",
    )
    parser.add_argument(
        "--max-slope-deg",
        type=float,
        default=25.0,
        help="Reject candidates steeper than this (default: 25).",
    )
    parser.add_argument(
        "--min-separation-m",
        type=float,
        default=300.0,
        help="Minimum distance between two candidates, metres (default: 300).",
    )
    parser.add_argument(
        "--skip-candidates",
        action="store_true",
        help="Ingest the DEM only; do not generate candidate sites.",
    )
    parser.add_argument(
        "--skip-viewsheds",
        action="store_true",
        help="Stop after candidate generation; do not queue viewsheds.",
    )
    parser.add_argument(
        "--observer-height-m", type=float, default=10.0, help="Sentinel pole height (default: 10)."
    )
    parser.add_argument(
        "--target-height-m",
        type=float,
        default=0.0,
        help="Height of what must be seen, e.g. smoke (default: 0).",
    )
    parser.add_argument(
        "--viewshed-max-distance-m",
        type=float,
        default=5_000.0,
        help="Sentinel sight range, metres (default: 5000).",
    )
    return parser.parse_args(argv)


def study_area_from_raster(path: Path, inset: float) -> dict[str, Any]:
    """Build a study area in EPSG:4326 covering the middle of a raster."""
    with rasterio.open(path) as dataset:
        left, bottom, right, top = dataset.bounds
        crs = dataset.crs
        if crs is None:
            msg = f"{path} has no CRS; it cannot be used to derive a study area"
            raise SystemExit(msg)
        crs_text = crs.to_string()

    inset_x = (right - left) * inset
    inset_y = (top - bottom) * inset
    inner = box(left + inset_x, bottom + inset_y, right - inset_x, top - inset_y)
    return dict(mapping(reproject_geometry(inner, crs_text, "EPSG:4326")))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base = args.api_url.rstrip("/")

    with tempfile.TemporaryDirectory() as tmp:
        if args.dem is not None:
            dem_path = args.dem
            if not dem_path.is_file():
                print(f"{dem_path} does not exist.", file=sys.stderr)
                return 1
            description = f"Study area over {dem_path.name}."
        else:
            dem_path = Path(tmp) / "demo_dem_synthetic.tif"
            write_synthetic_dem(
                dem_path,
                SyntheticDemSpec(width=400, height=400, resolution_m=25.0, seed=20240101),
            )
            description = (
                "Demonstration project. The terrain is synthetic, not a survey of a real place."
            )

        area = study_area_from_raster(dem_path, args.inset)

        with httpx2.Client(base_url=base, timeout=120.0) as client:
            created = client.post(
                f"{API_PREFIX}/projects",
                json={"name": args.name, "description": description, "area": area},
            )
            if created.status_code != 201:
                print(
                    f"Creating the project failed: {created.status_code} {created.text}",
                    file=sys.stderr,
                )
                return 1
            project = created.json()

            with dem_path.open("rb") as handle:
                ingested = client.post(
                    f"{API_PREFIX}/projects/{project['id']}/datasets",
                    files={"file": (dem_path.name, handle, "image/tiff")},
                    data={"buffer_m": str(args.buffer_m)},
                )
            if ingested.status_code != 201:
                print(f"Ingestion failed: {ingested.status_code} {ingested.text}", file=sys.stderr)
                return 1
            result = ingested.json()

            candidate_run: dict[str, Any] | None = None
            if not args.skip_candidates:
                generated = client.post(
                    f"{API_PREFIX}/projects/{project['id']}/candidates",
                    json={
                        "spacing_m": args.spacing_m,
                        "max_slope_deg": args.max_slope_deg,
                        "min_separation_m": args.min_separation_m,
                    },
                )
                if generated.status_code != 201:
                    print(
                        f"Candidate generation failed: {generated.status_code} {generated.text}",
                        file=sys.stderr,
                    )
                    return 1
                candidate_run = generated.json()

            viewshed_run: dict[str, Any] | None = None
            if candidate_run is not None and not args.skip_viewsheds:
                queued = client.post(
                    f"{API_PREFIX}/analysis-runs/{candidate_run['id']}/viewsheds",
                    json={
                        "observer_height_m": args.observer_height_m,
                        "target_height_m": args.target_height_m,
                        "max_distance_m": args.viewshed_max_distance_m,
                    },
                )
                if queued.status_code != 202:
                    print(
                        f"Queuing viewsheds failed: {queued.status_code} {queued.text}",
                        file=sys.stderr,
                    )
                    return 1
                viewshed_run = queued.json()

    summary: dict[str, Any] = {
        "project_id": project["id"],
        "analysis_crs": project["analysis_crs"],
        "area_km2": round(project["area_km2"], 2),
        "raw_dataset_id": result["raw"]["id"],
        "processed_dataset_id": result["processed"]["id"],
        "processed_crs": result["processed"]["crs"],
        "processed_resolution_m": result["processed"]["resolution_x"],
        "coverage_ratio": result["validation"]["coverage_ratio"],
        "preview_url": f"{base}{result['preview_url']}",
        "project_page": f"/projects/{project['id']}",
    }
    if candidate_run is not None:
        summary["candidate_run_id"] = candidate_run["id"]
        summary["candidate_count"] = candidate_run["metrics"]["candidate_count"]
        summary["grid_point_count"] = candidate_run["metrics"]["grid_point_count"]
    if viewshed_run is not None:
        summary["viewshed_run_id"] = viewshed_run["id"]
        summary["viewshed_run_status"] = viewshed_run["status"]
        summary["viewsheds_queued"] = viewshed_run["metrics"]["total"]
        summary["viewsheds_cache_hits"] = viewshed_run["metrics"]["cache_hits"]
        summary["note"] = (
            "Viewsheds are queued, not computed. Ensure a worker is running "
            "(make dev-worker, or the 'worker' Compose service) and poll "
            f"GET /api/v1/analysis-runs/{viewshed_run['id']} for status=completed."
        )

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
