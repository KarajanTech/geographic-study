"""Figures and the self-contained HTML report.

Colors are pulled verbatim from the house data-viz palette (validated
categorical/sequential hues, chart chrome) rather than invented here: blue
for the single coverage series/overlay, orange for selected-mast markers (a
distinct hue from the coverage wash), muted gray for unselected candidates.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from affine import Affine
from matplotlib.colors import LightSource, to_rgba
from matplotlib.figure import Figure

from .config import StudyConfig

CHART_SURFACE = "#fcfcfb"
PRIMARY_INK = "#0b0b0b"
SECONDARY_INK = "#52514e"
MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

DISCLAIMER = (
    "This report shows GEOMETRIC line-of-sight coverage only, computed from public "
    "elevation and land-cover data. It is not a smoke-detection-probability model -- "
    "actual detection also depends on plume size, atmospheric visibility and camera "
    "zoom, none of which are represented here. Canopy heights are a heuristic derived "
    "from land-cover class, not a measured product. Treat this as a preliminary "
    "screening layer, not a substitute for field validation."
)


@dataclass
class SentinelReportRow:
    rank: int
    x: float
    y: float
    lon: float
    lat: float
    elevation_m: float
    local_canopy_height_m: float
    marginal_coverage_pct: float
    cumulative_coverage_pct: float


def _raster_extent(shape: tuple[int, int], transform: Affine) -> tuple[float, float, float, float]:
    height, width = shape
    resolution_m = abs(transform.a)
    minx = transform.c
    maxy = transform.f
    maxx = minx + width * resolution_m
    miny = maxy - height * resolution_m
    return minx, maxx, miny, maxy


def _style_axes(ax) -> None:
    ax.set_facecolor(CHART_SURFACE)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_visible(False)


def hillshade_figure(
    bare_earth_m: np.ndarray,
    transform: Affine,
    coverage_union_mask: np.ndarray | None = None,
    selected_xy: np.ndarray | None = None,
    candidate_xy: np.ndarray | None = None,
    title: str = "Coverage map",
) -> Figure:
    resolution_m = abs(transform.a)
    ls = LightSource(azdeg=315, altdeg=45)
    hillshade = ls.hillshade(bare_earth_m, vert_exag=2.0, dx=resolution_m, dy=resolution_m)
    extent = _raster_extent(bare_earth_m.shape, transform)

    fig, ax = plt.subplots(figsize=(9, 8), dpi=150, facecolor=CHART_SURFACE, constrained_layout=True)
    _style_axes(ax)
    ax.imshow(hillshade, cmap="gray", vmin=0, vmax=1, extent=extent, origin="upper", zorder=1)

    if coverage_union_mask is not None:
        overlay = np.zeros((*coverage_union_mask.shape, 4), dtype=np.float32)
        overlay[coverage_union_mask] = to_rgba(BLUE, 0.40)
        ax.imshow(overlay, extent=extent, origin="upper", zorder=2)

    if candidate_xy is not None and len(candidate_xy):
        ax.scatter(
            candidate_xy[:, 0], candidate_xy[:, 1], s=4, color=MUTED, alpha=0.45, linewidths=0,
            zorder=3, label="Candidate position",
        )

    if selected_xy is not None and len(selected_xy):
        ax.scatter(
            selected_xy[:, 0], selected_xy[:, 1], s=100, color=ORANGE, edgecolors="white",
            linewidths=1.3, zorder=4, label="Selected Sentinel",
        )
        for i, (x, y) in enumerate(selected_xy, start=1):
            ax.annotate(
                str(i), (x, y), textcoords="offset points", xytext=(0, 9), ha="center",
                fontsize=8, color=PRIMARY_INK, fontweight="bold", zorder=5,
            )

    ax.set_xlabel("Easting (m)", color=SECONDARY_INK, fontsize=9)
    ax.set_ylabel("Northing (m)", color=SECONDARY_INK, fontsize=9)
    ax.set_title(title, color=PRIMARY_INK, fontsize=13, fontweight="bold", loc="left")
    if selected_xy is not None and len(selected_xy):
        legend = ax.legend(
            loc="lower right", fontsize=8, framealpha=0.9, facecolor=CHART_SURFACE, edgecolor=BASELINE
        )
        for text in legend.get_texts():
            text.set_color(SECONDARY_INK)
    return fig


def coverage_vs_n_chart(
    marginal_gain_history: list[float],
    cumulative_coverage_frac_history: list[float],
) -> Figure:
    n = np.arange(1, len(cumulative_coverage_frac_history) + 1)
    cumulative_pct = np.array(cumulative_coverage_frac_history) * 100.0
    marginal_pct = np.diff(np.concatenate([[0.0], cumulative_pct]))

    fig, (ax_cum, ax_marg) = plt.subplots(
        2, 1, figsize=(7.5, 6.5), dpi=150, sharex=True, facecolor=CHART_SURFACE, constrained_layout=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )
    for ax in (ax_cum, ax_marg):
        _style_axes(ax)
        ax.grid(True, axis="y", color=GRIDLINE, linewidth=0.8, zorder=0)

    ax_cum.plot(
        n, cumulative_pct, color=BLUE, linewidth=2.5, marker="o", markersize=8,
        markerfacecolor=BLUE, markeredgecolor=CHART_SURFACE, markeredgewidth=1.2, zorder=3,
    )
    ax_cum.set_ylim(0, max(100.0, float(cumulative_pct.max()) * 1.1))
    ax_cum.set_ylabel("Cumulative coverage (%)", color=SECONDARY_INK, fontsize=9)
    ax_cum.set_title(
        "Coverage vs. number of Sentinel masts", color=PRIMARY_INK, fontsize=13, fontweight="bold", loc="left"
    )
    ax_cum.annotate(
        f"{cumulative_pct[-1]:.0f}%", (n[-1], cumulative_pct[-1]), textcoords="offset points",
        xytext=(8, 2), fontsize=10, color=PRIMARY_INK, fontweight="bold",
    )

    ax_marg.bar(n, marginal_pct, color=BLUE, width=0.6, zorder=3)
    ax_marg.set_ylabel("Added per mast (pp)", color=SECONDARY_INK, fontsize=9)
    ax_marg.set_xlabel("Number of Sentinel masts", color=SECONDARY_INK, fontsize=9)
    ax_marg.set_xticks(n)
    if len(n) > 20:
        ax_marg.set_xticks(n[:: max(1, len(n) // 15)])

    return fig


def _fig_to_base64_png(fig: Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_html_report(
    output_path: Path,
    config: StudyConfig,
    rows: list[SentinelReportRow],
    hillshade_fig: Figure,
    elbow_fig: Figure,
    diagnostics: dict[str, object],
) -> None:
    hillshade_b64 = _fig_to_base64_png(hillshade_fig)
    elbow_b64 = _fig_to_base64_png(elbow_fig)

    lon_min, lat_min, lon_max, lat_max = config.area.resolve_bbox_wgs84()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    table_rows = "\n".join(
        f"<tr><td>{r.rank}</td><td>{r.lat:.5f}, {r.lon:.5f}</td><td>{r.elevation_m:.0f} m</td>"
        f"<td>{r.local_canopy_height_m:.0f} m</td><td>+{r.marginal_coverage_pct:.1f} pp</td>"
        f"<td>{r.cumulative_coverage_pct:.1f}%</td></tr>"
        for r in rows
    )
    diagnostics_rows = "\n".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in diagnostics.items())
    final_coverage = rows[-1].cumulative_coverage_pct if rows else 0.0

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Karajan Geographic Study -- Sentinel Coverage Report</title>
<style>
  :root {{
    color-scheme: light dark;
    --surface-1: #fcfcfb; --page: #f9f9f7; --ink: #0b0b0b; --ink-2: #52514e;
    --muted: #898781; --border: rgba(11,11,11,0.10); --card: #ffffff;
    --accent: {BLUE}; --warn-bg: #fff4ea; --warn-border: #eb6834;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --surface-1: #1a1a19; --page: #0d0d0d; --ink: #ffffff; --ink-2: #c3c2b7;
      --muted: #898781; --border: rgba(255,255,255,0.10); --card: #16181c;
      --warn-bg: #2a1f14; --warn-border: #d95926;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2.5rem 1.25rem 4rem; background: var(--page); color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.5;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 0.25rem; }}
  .subtitle {{ color: var(--ink-2); font-size: 0.95rem; margin-bottom: 1.75rem; }}
  .disclaimer {{
    background: var(--warn-bg); border-left: 3px solid var(--warn-border);
    padding: 0.9rem 1.1rem; border-radius: 4px; font-size: 0.88rem; color: var(--ink-2);
    margin-bottom: 2rem;
  }}
  .disclaimer strong {{ color: var(--ink); }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 1.25rem; margin-bottom: 1.75rem;
  }}
  .card img {{ width: 100%; height: auto; border-radius: 6px; background: {CHART_SURFACE}; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 0.9rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  td:first-child, th:first-child {{ padding-left: 0; }}
  .params {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem 1.5rem; font-size: 0.85rem; }}
  .params dt {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; }}
  .params dd {{ margin: 0.15rem 0 0; font-weight: 600; }}
  .headline {{ font-size: 2rem; font-weight: 700; color: var(--accent); }}
  footer {{ color: var(--muted); font-size: 0.78rem; margin-top: 2rem; }}
  footer a {{ color: var(--ink-2); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Karajan Geographic Study &mdash; Sentinel Coverage Report</h1>
  <div class="subtitle">Generated {generated_at} &middot; AOI [{lat_min:.4f}, {lon_min:.4f}] to [{lat_max:.4f}, {lon_max:.4f}]</div>

  <div class="disclaimer"><strong>Read this first:</strong> {DISCLAIMER}</div>

  <div class="card">
    <h2>Study parameters</h2>
    <dl class="params">
      <div><dt>Mast height</dt><dd>{config.sensor.mast_height_m:.0f} m</dd></div>
      <div><dt>Target height</dt><dd>{config.sensor.target_height_m:.0f} m above ground</dd></div>
      <div><dt>Max range</dt><dd>{config.sensor.max_range_m / 1000:.1f} km</dd></div>
      <div><dt>Candidate spacing</dt><dd>{config.grid.candidate_spacing_m:.0f} m</dd></div>
      <div><dt>Eval resolution</dt><dd>{config.grid.eval_resolution_m:.0f} m</dd></div>
      <div><dt>Rays per candidate</dt><dd>{config.grid.resolved_n_rays(config.sensor.max_range_m)}</dd></div>
    </dl>
  </div>

  <div class="card">
    <h2>Result: {len(rows)} Sentinel mast{"s" if len(rows) != 1 else ""} &rarr; <span class="headline">{final_coverage:.0f}%</span> weighted coverage</h2>
    <img src="data:image/png;base64,{elbow_b64}" alt="Coverage vs number of Sentinel masts">
  </div>

  <div class="card">
    <h2>Proposed Sentinel locations and coverage map</h2>
    <img src="data:image/png;base64,{hillshade_b64}" alt="Hillshade map with coverage overlay and selected mast positions">
  </div>

  <div class="card">
    <h2>Proposed Sentinel locations</h2>
    <table>
      <thead><tr><th>#</th><th>Lat, Lon</th><th>Ground elev.</th><th>Local canopy</th><th>Marginal</th><th>Cumulative</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>Run diagnostics</h2>
    <table>
      <tbody>{diagnostics_rows}</tbody>
    </table>
  </div>

  <footer>
    Elevation: Mapzen/AWS Terrarium terrain tiles (SRTM-derived). Land cover: ESA WorldCover
    10m v200 (2021), &copy; ESA. Geometric line-of-sight coverage model with earth-curvature
    and standard-refraction correction (k=0.13); no claim of actual smoke-detection range.
  </footer>
</div>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
