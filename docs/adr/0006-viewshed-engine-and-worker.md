# ADR 0006: Viewshed engine, caching, and worker execution

- Status: accepted
- Date: 2026-07-25
- Phase: 3
- Extends: [ADR 0002](0002-monorepo-and-toolchain.md), [ADR 0003](0003-metric-crs-and-immutable-data.md), [ADR 0005](0005-candidate-generation.md)

## Context

Phase 3 answers, for each candidate from Phase 2, which cells of the terrain it
can actually see. `ARCHITECTURE.md` §7 sketches a `ViewshedEngine` interface
with GDAL's own viewshed generator as the recommended implementation, a cache
keyed on surface checksum and observer parameters, and a compact storage
format. The non-negotiable rules add: never compute a viewshed inside an HTTP
request, execute it in a worker, and cache repeated computations.

## Decisions

### The algorithm is a NumPy radial line-of-sight sweep, not GDAL's

`osgeo` (GDAL's Python bindings) is not installed alongside the `rasterio`
wheels this project depends on, and ADR 0002 deliberately avoided a system GDAL
requirement for onboarding. Adding a separate `gdal` PyPI package would bundle
a second private copy of libgdal in the same process as rasterio's — a known
source of ABI conflicts — for a dependency whose only purpose here is an
interface the architecture already asks to keep swappable.

`app.geo.viewshed.LineOfSightViewshedEngine` implements the interface instead:
for a set of angles around the observer, it walks outward in half-cell steps
and keeps a running horizon angle built from bare terrain; a point is visible
when its own angle (terrain elevation plus `target_height_m`) meets or exceeds
that horizon. This is the same family of algorithm GDAL and GRASS's
`r.viewshed` use (radial/angular sweep with a horizon profile), implemented
directly against the surfaces this pipeline already produces.

Two details matter for correctness:

- **The horizon is built from bare terrain, `target_height_m` is applied only
  to the point being tested.** An obstacle's blocking height does not depend
  on how tall the thing we are trying to see elsewhere is. Baking
  `target_height_m` into the horizon itself was tried first and produced the
  opposite of the intended effect — raising the target height _reduced_
  visibility, because it inflated the ridge's own apparent height along with
  everything else. Caught by the Phase 3 critical test itself
  ("cambiar la altura objetivo modifica la cobertura").
- **Earth curvature and refraction** apply the standard correction —
  `distance² × (1 − refraction_coefficient) / (2 × earth_radius)` subtracted
  from apparent elevation — configurable and part of the cache key, per
  `ARCHITECTURE.md` §7.

`ViewshedEngine` stays an abstract interface specifically so a GDAL-backed
implementation can be added and compared later without touching the service
layer, per the architecture's own reasoning for the abstraction.

### PostgreSQL is the job queue

Rather than introduce Redis/Celery/RQ now, `AnalysisRun` (kind=viewshed) and
`Viewshed` rows are written at `pending` by the enqueue endpoint and picked up
by a poll loop. `app.services.viewsheds.process_pending_viewshed_runs` is that
poll loop's body — callable directly (tests do this to simulate the worker) or
run forever by `app.workers.viewshed_worker`, now its own Docker Compose
service and `make dev-worker` target on the host.

This keeps "avoid unnecessary microservices" true while still giving Phase 3
what its own roadmap task list asks for: viewshed computation never runs
inside the HTTP request that queues it, and a real out-of-process worker does
the work. A message broker is a reasonable future upgrade if throughput ever
demands it; nothing here blocks that migration, since the queue is entirely
behind `process_pending_viewshed_runs`.

### The cache key is exactly what the architecture specifies, plus the algorithm version

`compute_cache_key` hashes `(algorithm_version, surface_checksum, observer_x,
observer_y, observer_height_m, target_height_m, max_distance_m,
curvature_setting, refraction_coefficient)`, matching `ARCHITECTURE.md` §7's
listed fields. `algorithm_version` is included so swapping in a GDAL-backed
engine later invalidates the cache rather than silently mixing results from
two algorithms. `Viewshed.cache_key` is a unique database column: enqueuing a
request whose key already exists reuses that row instead of creating a new
one, satisfying "repetir un cálculo idéntico utiliza la caché" without a
separate cache layer — PostgreSQL's unique index is the cache.

### A failed candidate does not fail the batch

`process_pending_viewshed_runs` catches per-candidate exceptions, marks that
one `Viewshed` row `failed` with its error message, and continues; the batch
`AnalysisRun` finishes `completed` with the failure counted in its metrics.
This is the same pattern Phase 8's CP-SAT fallback will use at a coarser
grain — a partial result is always preferable to losing the whole run over one
bad input.

### Two artefacts per viewshed, matching `ARCHITECTURE.md` §8

A compressed single-band GeoTIFF (`raster_uri`) for export and inspection, and
a `numpy.packbits` array (`bitset_uri`) for the fast bitwise coverage
combination Phase 4's optimizer will need. A third, presentation-only overlay
PNG (`preview_uri`) exists purely so the frontend can show a viewshed without
reprojecting or interpreting a GeoTIFF client-side — no visibility figure the
page displays comes from that image; every one comes from the `Viewshed` row.

### A synchronous "process now" path exists for demos and tests only

`process_pending_viewshed_runs` is exposed as a plain function, not only
reachable via the worker container. Tests call it directly to simulate the
worker deterministically, and `scripts/seed_demo_project.py` could too, if a
demo needs results without waiting for the compose worker's poll interval.
This does not reintroduce synchronous-in-request computation: the HTTP enqueue
endpoint never calls it, and the only production path is the worker's own loop.

## Consequences

- No new runtime dependency: still GDAL-via-rasterio, still PostgreSQL, still
  Docker Compose with one more service.
- A viewshed's provenance is complete: which surface (by checksum), which
  candidate, which parameters, which algorithm version.
- Recomputing an unchanged project's viewsheds after a restart costs nothing —
  the cache key finds the existing rows.
- Phase 4's optimizer can read `bitset_uri` for every candidate of a run and
  combine them with NumPy bitwise operations, without touching this module.
- If GDAL's viewshed is ever wanted for comparison or higher fidelity, it is a
  second `ViewshedEngine` implementation and a config switch, not a rewrite.
