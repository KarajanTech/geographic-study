"""CLI: run the full pipeline end to end for a given area and sensor spec.

    python -m sentinel_coverage.run_study                     # Montseny demo
    python -m sentinel_coverage.run_study --bbox 2.35 41.75 2.50 41.85
    python -m sentinel_coverage.run_study --center 2.43 41.80 --radius-km 6
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform
from rasterio.warp import transform_bounds

from . import candidates as candidates_mod
from . import landcover, optimize, report, terrain, viewshed
from .config import DEMO_STUDY_AREA, GridSpec, SensorSpec, StudyArea, StudyConfig

WGS84 = CRS.from_epsg(4326)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    area = p.add_mutually_exclusive_group()
    area.add_argument("--bbox", type=float, nargs=4, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    area.add_argument("--center", type=float, nargs=2, metavar=("LON", "LAT"))
    p.add_argument("--radius-km", type=float, default=6.0, help="required with --center")

    p.add_argument("--mast-height", type=float, default=18.0, help="meters above bare ground")
    p.add_argument(
        "--target-height", type=float, default=25.0,
        help="meters above bare ground a point must reach to count as covered "
             "(default models smoke rising above the tree line, not bare ground itself)",
    )
    p.add_argument("--max-range-km", type=float, default=15.0)

    p.add_argument("--spacing-m", type=float, default=400.0, help="candidate grid spacing")
    p.add_argument("--eval-resolution-m", type=float, default=30.0)
    p.add_argument(
        "--n-rays", type=int, default=None,
        help="default: auto, scaled so ray spacing at max range doesn't exceed eval resolution "
             "(too few rays speckles the coverage map -- see GridSpec.resolved_n_rays)",
    )
    p.add_argument("--zoom", type=int, default=12, help="Terrarium tile zoom level")

    stop = p.add_mutually_exclusive_group()
    stop.add_argument("--max-sentinels", type=int, default=15)
    stop.add_argument("--target-coverage", type=float, help="fraction 0-1, overrides --max-sentinels")
    p.add_argument("--min-marginal-gain", type=float, default=0.005, help="stop early below this per-step gain")

    p.add_argument("--cache-dir", default="~/.cache/sentinel_coverage")
    p.add_argument("--output", default="output/report.html")
    return p


def _config_from_args(args: argparse.Namespace) -> StudyConfig:
    if args.bbox is not None:
        area = StudyArea(bbox=tuple(args.bbox))
    elif args.center is not None:
        area = StudyArea(center_lon=args.center[0], center_lat=args.center[1], radius_km=args.radius_km)
    else:
        area = DEMO_STUDY_AREA

    sensor = SensorSpec(
        mast_height_m=args.mast_height,
        target_height_m=args.target_height,
        max_range_m=args.max_range_km * 1000.0,
    )
    grid = GridSpec(
        eval_resolution_m=args.eval_resolution_m,
        candidate_spacing_m=args.spacing_m,
        n_rays=args.n_rays,
    )
    max_sentinels = None if args.target_coverage is not None else args.max_sentinels
    return StudyConfig(
        area=area,
        sensor=sensor,
        grid=grid,
        terrarium_zoom=args.zoom,
        cache_dir=args.cache_dir,
        max_sentinels=max_sentinels,
        target_coverage=args.target_coverage,
        min_marginal_gain_frac=args.min_marginal_gain,
    )


def run_study(config: StudyConfig, output_path: Path) -> dict[str, object]:
    t0 = time.perf_counter()
    aoi_bbox = config.area.resolve_bbox_wgs84()
    cache_dir = Path(config.cache_dir).expanduser()

    print(f"[1/6] Fetching elevation for AOI + {config.sensor.max_range_m / 1000:.1f}km halo...")
    bare_earth_m, dst_transform, utm_crs = terrain.fetch_dem_utm(
        aoi_bbox, config.sensor.max_range_m, config.terrarium_zoom, cache_dir, config.grid.eval_resolution_m
    )
    print(f"      DEM grid: {bare_earth_m.shape[1]}x{bare_earth_m.shape[0]} px @ {config.grid.eval_resolution_m:.0f}m, "
          f"elevation {np.nanmin(bare_earth_m):.0f}-{np.nanmax(bare_earth_m):.0f}m ({time.perf_counter() - t0:.1f}s)")

    print("[2/6] Fetching land cover (ESA WorldCover)...")
    class_codes = landcover.fetch_landcover_class_utm(
        aoi_bbox, config.sensor.max_range_m, dst_transform, bare_earth_m.shape, utm_crs
    )
    canopy_height_m = landcover.canopy_height_from_classes(class_codes)
    coverage_weight = landcover.coverage_weight_from_classes(class_codes)
    print(f"      canopy height up to {canopy_height_m.max():.0f}m ({time.perf_counter() - t0:.1f}s)")

    grids = viewshed.build_viewshed_grids(bare_earth_m, canopy_height_m, dst_transform, utm_crs, aoi_bbox)
    row0, row1, col0, col1 = grids.eval_window
    eval_transform = dst_transform * Affine.translation(col0, row0)
    cell_weight_2d = coverage_weight[row0:row1, col0:col1] * (config.grid.eval_resolution_m**2)
    cell_weights = cell_weight_2d.reshape(-1)

    print("[3/6] Generating candidate mast positions...")
    aoi_bounds_utm = transform_bounds(WGS84, utm_crs, *aoi_bbox)
    candidate_xy = candidates_mod.generate_candidate_grid(aoi_bounds_utm, config.grid.candidate_spacing_m)
    keep_mask = candidates_mod.filter_candidates(candidate_xy, bare_earth_m, class_codes, dst_transform)
    n_dropped = int((~keep_mask).sum())
    candidate_xy = candidate_xy[keep_mask]
    candidate_elev = candidates_mod.attach_elevation(candidate_xy, bare_earth_m, dst_transform)
    print(f"      {len(candidate_xy)} candidates ({n_dropped} dropped as water) ({time.perf_counter() - t0:.1f}s)")

    n_rays = config.grid.resolved_n_rays(config.sensor.max_range_m)
    print(f"[4/6] Computing viewsheds ({n_rays} rays each)...")
    candidate_masks, total_oob = viewshed.compute_viewshed_batch(
        grids, [tuple(xy) for xy in candidate_xy], config.sensor,
        n_rays=n_rays, ray_step_m=config.grid.resolved_ray_step_m(),
    )
    if total_oob:
        print(f"      warning: {total_oob} ray samples fell outside loaded terrain (halo buffer diagnostic)")
    print(f"      done ({time.perf_counter() - t0:.1f}s)")

    print("[5/6] Optimizing mast placement (greedy max-coverage)...")
    result = optimize.greedy_max_coverage(
        candidate_masks, cell_weights, k=config.max_sentinels,
        target_coverage=config.target_coverage, min_marginal_gain_frac=config.min_marginal_gain_frac,
    )
    final_pct = result.cumulative_coverage_frac_history[-1] * 100 if result.cumulative_coverage_frac_history else 0.0
    print(f"      selected {len(result.selected_indices)} mast(s), {final_pct:.1f}% weighted coverage "
          f"({time.perf_counter() - t0:.1f}s)")

    print("[6/6] Rendering report...")
    selected_xy = candidate_xy[result.selected_indices]
    lons, lats = warp_transform(utm_crs, WGS84, selected_xy[:, 0].tolist(), selected_xy[:, 1].tolist())
    local_canopy = candidates_mod.sample_raster_at_points(canopy_height_m, dst_transform, selected_xy, order=0)
    cumulative_pct = [f * 100.0 for f in result.cumulative_coverage_frac_history]
    marginal_pct = [cumulative_pct[i] - (cumulative_pct[i - 1] if i else 0.0) for i in range(len(cumulative_pct))]

    rows = [
        report.SentinelReportRow(
            rank=i + 1,
            x=float(selected_xy[i, 0]), y=float(selected_xy[i, 1]),
            lon=float(lons[i]), lat=float(lats[i]),
            elevation_m=float(candidate_elev[result.selected_indices[i]]),
            local_canopy_height_m=float(local_canopy[i]),
            marginal_coverage_pct=marginal_pct[i],
            cumulative_coverage_pct=cumulative_pct[i],
        )
        for i in range(len(result.selected_indices))
    ]

    coverage_union_mask = result.covered_mask.reshape(grids.eval_shape)
    bare_earth_eval = bare_earth_m[row0:row1, col0:col1]
    hillshade_fig = report.hillshade_figure(
        bare_earth_eval, eval_transform, coverage_union_mask=coverage_union_mask,
        selected_xy=selected_xy, candidate_xy=candidate_xy,
        title=f"{len(rows)} Sentinel mast{'s' if len(rows) != 1 else ''} -- {final_pct:.0f}% weighted coverage",
    )
    elbow_fig = report.coverage_vs_n_chart(result.marginal_gain_history, result.cumulative_coverage_frac_history)

    diagnostics = {
        "Candidates evaluated": len(candidate_xy),
        "Candidates dropped (water)": n_dropped,
        "Eval grid": f"{grids.eval_shape[1]} x {grids.eval_shape[0]} px @ {config.grid.eval_resolution_m:.0f}m",
        "Out-of-bounds ray samples": total_oob,
        "Total runtime": f"{time.perf_counter() - t0:.1f}s",
    }
    report.render_html_report(output_path, config, rows, hillshade_fig, elbow_fig, diagnostics)
    print(f"      wrote {output_path} ({time.perf_counter() - t0:.1f}s total)")

    return {"rows": rows, "diagnostics": diagnostics, "output_path": output_path}


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = _config_from_args(args)
    run_study(config, Path(args.output))
    return 0


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli()
