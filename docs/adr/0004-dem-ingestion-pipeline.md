# ADR 0004: DEM ingestion pipeline and analysis CRS selection

- Status: accepted
- Date: 2026-07-25
- Phase: 1
- Extends: [ADR 0003](0003-metric-crs-and-immutable-data.md)

## Context

Phase 1 turns an uploaded elevation model into the surface every later phase
computes on. Three decisions here determine whether the numbers produced in
Phase 3 and Phase 4 mean anything: which CRS the analysis runs in, how far past
the study area the surface must extend, and what counts as an acceptable DEM.

## Decisions

### The analysis CRS is chosen once, from the study area centroid

`app/geo/crs.select_analysis_crs` maps a centroid to a UTM zone:
ETRS89 / UTM (EPSG:258xx) inside the ETRS89 area of use, WGS84 / UTM
(EPSG:326xx / 327xx) elsewhere. ETRS89 is what Spanish cartography publishes,
which is the first market.

The rule is hand-written rather than delegated to `pyproj.query_utm_crs_info`,
so a PROJ database upgrade cannot silently change the CRS of an existing
project — reproducibility outranks convenience. Tests assert both the regional
answers and agreement with PROJ outside Europe.

The CRS is stored on the project and is **immutable**: datasets have already
been reprojected and clipped against it, so changing it would invalidate every
derived product. `PATCH /projects/{id}` accepts only name and description.

The caller may pin `analysis_crs` at creation, and it is validated as projected
and metre-based like any other.

### EPSG:4326 is for storage and display, never for measurement

Study areas arrive as GeoJSON in EPSG:4326 and geometries are stored in PostGIS
with SRID 4326. Every metric property — surface, perimeter, buffer distance —
is computed after projecting into the analysis CRS. Coordinates outside the
WGS84 ranges are rejected: it is the signal that someone pasted projected metres
into a degree field.

### The surface extends past the study area by a sight-range buffer

A Sentinel sees terrain outside the area it is meant to protect, and a viewshed
computed on a surface that stops at the boundary would report false blind spots
at the edges. The clip therefore uses the study area buffered by `buffer_m`
(default 15 km, matching the maximum sight range in `PRODUCT_SPEC.md`).

The buffer is a parameter, recorded in the dataset's processing history, not a
constant baked into the pipeline.

### Validation rejects on georeferencing, warns on data quality

Hard errors (ingestion refused): no CRS, no bands, degenerate grid, implausible
resolution for the declared unit, no intersection with the study area, coverage
below 50%.

Warnings (ingestion proceeds, recorded on the dataset): no declared nodata,
multi-band input, partial coverage.

The split follows what the operator can act on. A DEM without a CRS is
unusable. A DEM without nodata is usable but its gaps cannot be distinguished
from real elevations, and the operator needs to know that.

### Resampling is bilinear, and the intermediate is discarded

Elevation is a continuous surface: nearest-neighbour reprojection produces
artificial terraces that a viewshed then reads as real ridges. The reprojected
raster is written, clipped, and deleted — only the clipped analysis surface is
a product.

### Ingestion is synchronous in Phase 1, behind a service boundary

`app/services/ingestion.ingest_dem` takes paths and parameters and returns
paths and metadata. It touches neither HTTP nor the database, so Phase 3 can
hand it to a worker without a rewrite. A single DEM ingest is seconds of work;
viewsheds are what require the queue.

### Previews are display artefacts

The API serves a downsampled greyscale PNG with an alpha channel for nodata,
plus its EPSG:4326 bounds. Nothing is measured from the image: every figure the
frontend shows comes from the API. This is what keeps "no frontend-only
calculations for scientific results" true while still showing terrain.

## Consequences

- A project's CRS, buffer and parameters are all recorded, so an ingestion can
  be reproduced exactly.
- Changing a study area means creating a new project. That is deliberate.
- Storage holds roughly 2.5x the raw upload per DEM (analysis surface,
  hillshade, two previews).
- Phase 2 can assume: one surface per project, in metres, in a known CRS,
  extending past the study area by a known buffer.
