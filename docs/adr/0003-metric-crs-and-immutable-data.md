# ADR 0003: Metric CRS for every calculation, immutable raw data

- Status: accepted
- Date: 2026-07-25
- Phase: 0

## Context

The most damaging class of bug in this system is silent and unit-shaped: a
distance computed in degrees, a slope derived from a mismatched vertical unit, a
raster quietly overwritten so a result can no longer be reproduced. None of
these raise an exception; they produce plausible wrong numbers.

## Decision

**No metric calculation in a geographic CRS.** Distances, buffers, slopes, areas
and viewsheds run only on data in a projected CRS whose linear unit is the
metre. Code that writes or consumes a surface validates this and raises
`InvalidInputError` rather than assuming — `app/geo/sample_dem.py` already
rejects EPSG:4326 and foot-based projections, and it is tested both ways.

**Units are named, never implied.** Fields and parameters carry their unit in
the name (`resolution_m`, `observer_height_m`, `max_distance_m`), and rasters
carry `units` in their tags.

**Raw data is immutable.** `data/raw` holds uploads exactly as received;
derived products go to `data/processed`, exports to `data/outputs`. Every
dataset is identified by its SHA-256, which also anchors the viewshed cache key
defined in `ARCHITECTURE.md`.

**Every run records how it was produced.** `ALGORITHM_VERSION` is exposed by the
health endpoint from Phase 0 and will be stored with every `AnalysisRun`
together with its parameters and random seed. Randomness always takes an
explicit seed.

**Geospatial transformations are tested.** Any transformation — reprojection,
clipping, resampling, viewshed — needs a test asserting CRS, bounds, resolution
and units. Phase 0 sets the precedent with the sample DEM tests.

## Consequences

- A wrong CRS fails loudly and early instead of producing a wrong map.
- Re-running an analysis with the same configuration and seed reproduces it.
- Slightly more ceremony per dataset: worth it for results a client will act on.
