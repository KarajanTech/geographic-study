# ADR 0005: Candidate generation

- Status: accepted
- Date: 2026-07-25
- Phase: 2
- Extends: [ADR 0003](0003-metric-crs-and-immutable-data.md), [ADR 0004](0004-dem-ingestion-pipeline.md)

## Context

Before any visibility is computed, the system needs a manageable set of
positions to test. Phase 2 must turn a study area and a DEM into that set:
enough coverage of the terrain to find good sites, few enough that Phase 3's
viewshed engine can afford to run on every one of them.

This is purely a terrain question — no camera, no sightline, no coverage is
considered here. That is deliberate: it keeps candidate generation cheap
(seconds, not the minutes a viewshed batch will cost) and reusable across
different sensor configurations run against the same terrain.

## Decisions

### A regular grid, anchored to the study area, not the raster

`app/geo/candidates.build_grid` places points on a grid starting from the study
area's own bounding box, at the requested spacing, in the analysis CRS. Two
runs with the same area and spacing always produce the same grid — the raster
underneath does not affect it. Anchoring to the raster instead would mean two
DEMs of the same territory at different resolutions silently produce different
candidate grids.

An optional seeded jitter exists for later use (breaking up grid-aligned
artefacts in coverage overlap); it defaults to zero, so results stay a strict
grid unless asked otherwise.

### AnalysisRun is the reproducibility anchor for every pipeline stage

`ARCHITECTURE.md` §4 specifies `AnalysisRun` for exactly this. It now has a
real client: `kind=candidates` stores parameters (as JSON, including the seed),
algorithm version, status, timestamps and metrics. `CandidateSite` rows always
belong to a run, never floating free — a candidate without the parameters that
produced it is unauditable.

Rejected grid points are **not** persisted, only counted per reason in
`AnalysisRun.metrics.rejection_counts`. A coarse grid over a large area
produces far more rejections than acceptances; storing every one would dwarf
the useful data. The counts are what an operator reads to tune parameters
("80% rejected on slope — raise `max_slope_deg` or accept the loss").

Blocked sites are the exception: they are stored (`is_allowed=false`,
`filter_reasons=["blocked_site"]`) because they are operator input, not a grid
artefact, and the operator will want to see that their exclusion took effect.

### Hard filters vs. ranking

Filters that make a site physically unusable are hard rejections: outside the
study area, no elevation data, too steep, outside a configured elevation band,
inside an exclusion zone, blocked by the operator. A site failing any of these
is not persisted.

Prominence is not a filter — it is a **score**. It ranks accepted candidates so
that when thinning or a later optimizer must choose among nearby sites, the one
standing higher above its surroundings wins. This mirrors `ROADMAP.md`
Phase 2's "ordenar por elevación relativa o prominencia".

### Minimum separation is greedy and deterministic

Candidates are sorted (mandatory first, then by score, then by coordinates as a
tie-break) and accepted in that order; a site within `min_separation_m` of an
already-accepted site is dropped. A uniform spatial hash keeps the neighbour
search local rather than checking every pair.

The ordering is fixed and total (coordinates break every tie), so the result is
exactly reproducible — required by `PRODUCT_SPEC.md` §10 ("reproducir el mismo
resultado con la misma configuración y semilla") and `ROADMAP.md` Phase 2's
acceptance criterion that the same input produces the same candidates.

### Required and blocked sites are accepted as coordinates, not dataset uploads

`ARCHITECTURE.md` lists `existing_sites` as a dataset type for a later phase.
Phase 2 accepts required and blocked coordinates directly in the generation
request instead: they are a handful of points, not a raster, and forcing an
upload for them would be ceremony without benefit at this stage. A required
site bypasses every terrain filter (it is a fact, not a proposal) but is still
sampled for elevation, slope and prominence so it can be compared with the rest.

### Slope and prominence live next to hillshade

`app/geo/terrain.py` now holds three derivatives sharing one Horn gradient
implementation: hillshade (display only), slope (a hard filter) and local
prominence (a score). All three take cell size in metres explicitly — the
precedent set in ADR 0003 extends to every terrain calculation, not only
viewshed and buffering.

## Consequences

- A candidate set is fully reproducible from `(surface checksum, study area,
parameters, seed)`, satisfying the roadmap's reproducibility criterion
  without re-running the whole ingestion pipeline.
- Storage stays proportional to accepted candidates, not to grid resolution.
- Phase 3 receives a persisted, ranked candidate list per run and can compute
  viewsheds against exactly those points — no regeneration, no ambiguity about
  which surface or parameters produced them.
- Changing filter parameters means a new `AnalysisRun`, not a mutation of an
  existing one: old candidate sets remain inspectable after a re-run.
