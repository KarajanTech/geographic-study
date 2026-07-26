# ADR 0009: Risk-weighted coverage

- Status: accepted
- Date: 2026-07-25
- Phase: 6
- Extends: [ADR 0003](0003-metric-crs-and-immutable-data.md), [ADR 0007](0007-greedy-coverage-optimizer.md)

## Context

Phase 4's optimizer already took a `cell_weights` array as a first-class
parameter — deliberately, so Phase 6 could plug real weights in without
touching `solve_greedy`'s signature — but `build_candidate_cell_matrix` always
built it as `np.ones(...)`. `ROADMAP.md` Phase 6 asks for an uploadable risk
raster, presets, priority zones, weight normalization, and for physical vs.
weighted coverage to be reported and persisted separately. The last two were
already true by construction since Phase 4 (`coverage_ratio` is the plain
covered-cell fraction; `weighted_coverage_ratio` divides by `cell_weights`);
this phase is about actually producing a non-uniform `cell_weights`.

## Decisions

### A priorities raster is resampled onto the analysis DEM's exact grid, not independently reprojected

`build_candidate_cell_matrix` indexes every array — candidate masks, cell
weights — by the same `valid_flat_index` into the surface's own grid. A
priorities raster uploaded and processed through the DEM's own
reproject-then-clip pipeline (ADR for Phase 1) would produce _a_ grid in the
right CRS and resolution, but not necessarily the _same_ grid: independent
resampling can disagree by a fraction of a pixel, which is invisible on a map
but fatal for array-index alignment.

`app.geo.warp.resample_to_reference` reprojects a source raster directly onto
another raster's transform, width and height — the same "snap to a reference
grid" operation GIS tools call align/warp-to-match. `app.services.priorities`
uses it to align every uploaded priorities raster to the project's processed
DEM, so `build_candidate_cell_matrix` can treat it as a plain
`(height, width)` array indexed exactly like the elevation band it already
reads.

### Weights come from exactly one base source, then priority zones multiply on top

`build_candidate_cell_matrix` gained `priorities_array`, `preset` and
`priority_zone_geometries` parameters. `priorities_array` (an aligned raster)
and `preset` (a named built-in) are mutually exclusive base weights —
enforced in `OptimizationRunRequest` with a Pydantic model validator, so a
confusing "which one wins" question never reaches the matrix builder.
`priority_zone_geometries` then multiplies whichever base was chosen, per
zone, via `app.optimization.weights.apply_priority_zones`. This mirrors how
Phase 2's `exclusion_zones` already layer on top of the base candidate grid:
one primary mechanism, one additive/multiplicative refinement.

### Normalization is min-max to `[0, 1]`, always

`app.optimization.weights.normalize_weights` min-max normalizes any base
weight (raster or preset) before use. `ROADMAP.md` asks for normalization
explicitly; min-max was chosen over z-score or sum-to-one because it keeps
weights non-negative by construction (`solve_greedy` already rejects negative
weights) and keeps `1.0` meaning "the most important cell in this surface" —
an interpretable anchor a user can reason about, unlike a z-score. A constant
input (every cell identical) normalizes to uniform `1.0`s rather than
dividing by zero: there is no relative priority to express when nothing
varies, so falling back to Phase 4's default is the correct degenerate case,
not an error.

Priority zone multipliers are deliberately _not_ renormalized afterwards.
`solve_greedy` and the weighted-coverage ratio both divide by the weights'
own sum, so a zone multiplier already changes a cell's weight relative to the
rest of the surface regardless of the base weights' absolute scale —
renormalizing again would be redundant arithmetic, not a behavior change.

### Presets are transparent terrain proxies, not a wildfire-risk model

`app.optimization.weights.preset_weights` offers `ridge_priority` and
`valley_priority`, computed only from elevation (already available for every
project). This project has no vegetation, climate or ignition-history data —
inventing a scored "risk" from nothing would be exactly the fake production
data the non-negotiable rules forbid. Presets exist so `ROADMAP.md`'s "añadir
presets de riesgo" and "aumentar el peso de una zona puede cambiar la
solución" are demonstrable without requiring a raster upload; their docstring
says outright that they are illustrative, not a real risk model. A real
deployment supplies its own raster via the upload path instead.

### `weights_summary` records the recipe, not the weight array

`OptimizationSolution.weights_summary` (JSONB) stores what produced the
weights — `{"source": "preset", "preset": "ridge_priority", ...}` or
`{"source": "raster", "priorities_dataset_id": ...}`, plus any priority
zones' multipliers — satisfying "los pesos utilizados quedan guardados"
without duplicating a per-cell array that is already fully reconstructible
from the recipe plus the referenced dataset. This is the same reproducibility
pattern used everywhere else in this codebase: store parameters and inputs,
not derived arrays.

## Consequences

- `solve_greedy` and its persisted output shape are unchanged: Phase 4's
  `coverage_ratio` vs. `weighted_coverage_ratio` split already satisfied
  "cobertura física y ponderada se reportan separadamente" before this phase
  existed.
- A project can have at most one _active_ priorities raster at a time (the
  most recently ingested `ready` one — `get_active_priorities_dataset`), the
  same "most recent wins" convention the frontend already uses for the
  analysis DEM.
- Phase 7's cost penalty and Phase 8's redundancy reward extend
  `objective_value` without touching how weights are built here.
