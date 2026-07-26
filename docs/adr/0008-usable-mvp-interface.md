# ADR 0008: Usable MVP interface

- Status: accepted
- Date: 2026-07-25
- Phase: 5
- Extends: [ADR 0002](0002-monorepo-and-toolchain.md), [ADR 0007](0007-greedy-coverage-optimizer.md)

## Context

Phases 0-4 built a complete, correct pipeline reachable only through curl or
`scripts/seed_demo_project.py`. Phase 5's objective per `ROADMAP.md` is to
turn that engine into something a user completes end to end — draw a study
area, upload a DEM, configure and launch each analysis step, watch progress,
see the result on a map, export it — without a terminal. None of the specs
name a mapping library or prescribe how the frontend should track a
still-running backend job, so this ADR records the choices made to fill
those gaps.

## Decisions

### Leaflet with OpenStreetMap tiles, loaded imperatively, not `react-leaflet`

Nothing in `PRODUCT_SPEC.md` or `ARCHITECTURE.md` names a map library. Leaflet
was chosen because it needs no API key or billing account (OpenStreetMap's
tile server is free, attribution-only) — appropriate for an MVP demo — and
`leaflet-draw` gives polygon drawing/editing without writing hit-testing code
by hand.

`InteractiveMap` (`apps/web/components/interactive-map.tsx`) drives Leaflet
imperatively inside a single mount-time `useEffect`, rather than through
`react-leaflet`. React 19 is very new; avoiding a second library's React
version compatibility surface for a one-directional integration (React never
needs to read Leaflet's internal state back) keeps this simple. The component
takes `mode: "draw" | "view"` and is deliberately non-reactive to prop
changes after mount — the parent remounts it via `key` when the underlying
data changes (a new candidate run, a new solution) instead of the component
diffing and re-drawing its own layers. This matches "components should not
contain geospatial business logic": Leaflet only projects and draws figures
the API already computed, same as the schematic SVG map it replaces.

### A `next/dynamic` loader wrapper, because Leaflet touches `window` at import time

`leaflet`'s module runs environment feature-detection as soon as it is
imported, which crashes Next.js's server-side prerender pass
(`ReferenceError: window is not defined`) even though `InteractiveMap` itself
is a `"use client"` component — Next.js still evaluates a Client Component's
module on the server once, to produce the initial HTML. `next/dynamic` with
`ssr: false` is the documented escape hatch, but it cannot be called from a
Server Component. `interactive-map-loader.tsx` is a small `"use client"` file
that does nothing but that dynamic import; both the project-creation form and
the (Server Component) project detail page import `InteractiveMap` from the
loader, never from `interactive-map.tsx` directly.

### Export is a backend endpoint, not a frontend computation

`GET /optimization-solutions/{id}/export.geojson` and `.../export.csv`
(`app/services/optimization.py::build_solution_geojson` /
`build_solution_csv_rows`) serialize the already-persisted solution and its
candidates' stored geometry. Building the same FeatureCollection from
already-fetched JSON in the browser would have worked too — this isn't a
"calculation" in the sense the non-negotiable rules mean — but keeping it
server-side means there is exactly one place that defines what an export
contains, matching every other download in this codebase
(`datasetDownloadUrl`, `viewshedPreviewUrl`) and guaranteeing "las posiciones
exportadas coinciden con el mapa" by construction rather than by keeping two
implementations in sync.

### Progress is client-side polling plus `router.refresh()`, not websockets

`AnalysisProgress` polls `GET /analysis-runs/{id}` every 3 seconds while a run
is `pending`/`running`, for a smoothly updating progress bar, and calls
Next.js's `router.refresh()` the moment it leaves those states so the rest of
the (Server Component) page — the results table, the next step's form —
picks up the finished run without a manual reload. This reuses the polling
architecture Phase 3 already established for the worker
(`process_pending_viewshed_runs`) instead of introducing websockets or SSE for
a single progress bar; "avoid unnecessary microservices" applies here too.

### Every step is a thin form over an endpoint that already existed

`ProjectForm`, `DatasetUploadForm`, `CandidateForm`, `ViewshedForm` and
`OptimizationForm` add no new backend behaviour — Phases 0-4 already exposed
every one of these operations over HTTP. Each form is a plain controlled
`<form>` calling the typed API client and then `router.refresh()`; validation
beyond HTML5's (`required`, `min`/`max`) is left to the API, and its
`ApiError.message` is shown inline (`.form-error`) rather than a generic
failure banner, satisfying "los errores son comprensibles" without a new
error-handling framework.

## Consequences

- The frontend gained one real runtime dependency (`leaflet` + `leaflet-draw`)
  and no new backend dependency.
- Every parameter a user enters through a form is the same request body the
  API has accepted since its own phase — the UI cannot drift from the
  contract because it never introduces a new one.
- `study-area-map.tsx`, the Phase 1-4 schematic SVG map, is removed: nothing
  used it after `InteractiveMap` took over both the creation-time drawing
  surface and the results view.
- A user can now run the entire pipeline — create, ingest, generate, compute,
  optimize, export — from `/projects/new` onward without leaving the browser.
