# Development guide

## Requirements

| Tool     | Version | Notes                                     |
| -------- | ------- | ----------------------------------------- |
| Python   | 3.12    | Pinned in `apps/api/pyproject.toml`.      |
| uv       | >= 0.5  | Manages the virtualenv and the lock file. |
| Node.js  | >= 20   | npm workspaces.                           |
| Docker   | >= 24   | PostGIS, and the full stack with Compose. |
| GNU Make | any     | Task entry points.                        |

GDAL is not required on the host: `rasterio` ships its own binary wheels.

## First run

```bash
git clone <repo> && cd geographic-study
cp .env.example .env          # adjust POSTGRES_PASSWORD at least
make install                  # uv sync + npm install
make dev                      # database + API + web in Docker
```

Then open:

- web app: <http://localhost:3000>
- API docs: <http://localhost:8000/api/v1/docs>
- liveness: <http://localhost:8000/api/v1/health>
- readiness: <http://localhost:8000/api/v1/health/ready>

Apply migrations once the database is up:

```bash
make db-upgrade
```

## Running without Docker

The database still runs in Docker; the API and the web app run on the host:

```bash
docker compose up -d db
export SENTINEL_DATABASE_URL=postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel
make db-upgrade
make dev-api     # http://localhost:8000
make dev-web     # http://localhost:3000
make dev-worker  # processes queued viewsheds; without it they stay pending
```

## Everyday commands

| Command               | What it does                                                                                          |
| --------------------- | ----------------------------------------------------------------------------------------------------- |
| `make help`           | List every target.                                                                                    |
| `make fmt`            | Format Python (Ruff) and TypeScript (Prettier).                                                       |
| `make lint`           | Ruff and ESLint.                                                                                      |
| `make typecheck`      | mypy (strict) and `tsc --noEmit`.                                                                     |
| `make test`           | pytest.                                                                                               |
| `make test-cov`       | pytest with coverage.                                                                                 |
| `make check`          | Everything CI runs, locally.                                                                          |
| `make schemas`        | Re-export OpenAPI and regenerate the shared TypeScript types.                                         |
| `make sample-dem`     | Write a synthetic DEM to `data/raw`.                                                                  |
| `make demo-project`   | Create a project, ingest a synthetic DEM, generate candidates, queue viewsheds and run the optimizer. |
| `make dev-worker`     | Run the viewshed worker on the host.                                                                  |
| `make db-upgrade`     | Apply Alembic migrations.                                                                             |
| `make db-test-create` | Create the PostGIS database the test suite uses.                                                      |

Install the git hooks once:

```bash
uv run --project apps/api pre-commit install
```

## Tests and the database

Most tests are pure and need nothing. The ones that exercise the API against
PostGIS use `SENTINEL_TEST_DATABASE_URL` and **skip themselves** when no
database answers, so `make test` always runs. To run them locally:

```bash
make up               # PostGIS in Docker
make db-test-create   # one-off: create sentinel_test with the extension
make test             # all tests, database ones included
```

The schema for those tests comes from `Base.metadata`; CI runs
`alembic upgrade head` separately so the migrations themselves are also proven.

## Doing the whole flow from the browser (Phase 5)

No terminal required: open `/projects/new`, name the project and draw the
study area boundary on the map (Leaflet + OpenStreetMap tiles, `leaflet-draw`
for the polygon tool), then on the created project's page — in order — upload
a GeoTIFF DEM, generate candidates, queue viewsheds, and run the optimizer.
Each step is a plain form over the same endpoints described below; while
viewsheds are computing, the page polls and updates its own progress bar,
then refreshes itself once the run finishes — no manual reload. Once a
solution exists, export it as GeoJSON or CSV from the Optimization panel.

## Ingesting a DEM, generating candidates, computing viewsheds and optimizing

The same pipeline without a browser, via a script or curl directly:

```bash
make up && make dev-worker   # in one terminal: stack up, worker running
make demo-project            # in another: project + DEM + candidates + viewsheds + optimization
```

`scripts/seed_demo_project.py` polls the viewshed run until the worker
finishes it (or a timeout elapses) and then runs the greedy optimizer, so the
printed summary includes `optimization_solution_id`, `selected_count` and
`coverage_ratio` when the worker kept up. Pass `--skip-optimization` to stop
right after queuing viewsheds instead.

It prints the project id, preview URL and candidate/viewshed/optimization
counts. Open `/projects` in the web app to see the study area, its hillshaded
surface, the candidate sites, each computed viewshed as a translucent
overlay, and — once a solution exists — the selected Sentinels highlighted on
the map alongside the units-vs-coverage table.

With a real DEM, and custom parameters:

```bash
uv run --project apps/api python scripts/seed_demo_project.py \
  --dem data/raw/mdt25.tif --spacing-m 250 --max-slope-deg 20
```

Or over HTTP directly:

```bash
curl -X POST localhost:8000/api/v1/projects \
  -H 'content-type: application/json' \
  -d '{"name":"Sierra","area":{"type":"Polygon","coordinates":[[[-3.8,40.35],[-3.68,40.35],[-3.68,40.44],[-3.8,40.44],[-3.8,40.35]]]}}'

curl -X POST localhost:8000/api/v1/projects/<id>/datasets \
  -F file=@data/raw/mdt25.tif -F buffer_m=15000

curl -X POST localhost:8000/api/v1/projects/<id>/candidates \
  -H 'content-type: application/json' \
  -d '{"spacing_m": 250, "max_slope_deg": 20, "min_separation_m": 300}'

# <candidates-run-id> comes from the response above.
curl -X POST localhost:8000/api/v1/analysis-runs/<candidates-run-id>/viewsheds \
  -H 'content-type: application/json' \
  -d '{"observer_height_m": 10, "target_height_m": 0, "max_distance_m": 10000}'

# <viewshed-run-id> comes from the response above, once its viewsheds are
# completed (poll GET /analysis-runs/{id} until status=completed).
curl -X POST localhost:8000/api/v1/analysis-runs/<viewshed-run-id>/optimize \
  -H 'content-type: application/json' \
  -d '{"max_sites": 5, "target_coverage": null}'
```

DEM ingestion returns the raw dataset, the processed analysis surface, the
validation report and the preview URL. Candidate generation returns the
`AnalysisRun`, with `metrics.rejection_counts` explaining what was filtered out
and why; fetch `GET /analysis-runs/{id}/candidates` for the accepted sites
themselves.

Viewshed enqueueing returns a `202` immediately with the batch `AnalysisRun` at
`status=pending` (or `completed` if every candidate was already cached) —
nothing is computed inside that request. A worker
(`make dev-worker`, or the `worker` Compose service) polls PostgreSQL for
pending work and processes it; poll `GET /analysis-runs/{id}` for progress and
`GET /analysis-runs/{id}/viewsheds` for the results once it reaches
`completed`.

Optimization runs synchronously — `POST /analysis-runs/{viewshed_run_id}/optimize`
returns the finished `OptimizationSolution` in the same request, since the
greedy algorithm only does array arithmetic over already-computed viewsheds,
not ray casting. It rejects a run that is not `kind=viewshed` or that has no
completed viewsheds yet. Fetch it again later with
`GET /analysis-runs/{id}/optimization-solutions` or
`GET /optimization-solutions/{id}`.

Export a solution's selected Sentinels with
`GET /optimization-solutions/{id}/export.geojson` (a FeatureCollection) or
`GET /optimization-solutions/{id}/export.csv` — both serialize the persisted
solution directly, so they always match what the map and table show.

### Risk-weighted coverage (Phase 6)

By default every cell counts equally. To weight coverage by risk or
priority, `POST /analysis-runs/{viewshed_run_id}/optimize` accepts:

```bash
# Option 1: a preset, computed from the DEM's own elevation — illustrative,
# not a real risk model (see ADR 0009).
curl -X POST localhost:8000/api/v1/analysis-runs/<viewshed-run-id>/optimize \
  -H 'content-type: application/json' \
  -d '{"preset": "ridge_priority"}'

# Option 2: an uploaded risk raster, resampled onto the analysis DEM's exact
# grid so its cells line up with every viewshed.
curl -X POST localhost:8000/api/v1/projects/<project-id>/priorities \
  -F file=@risk.tif
curl -X POST localhost:8000/api/v1/analysis-runs/<viewshed-run-id>/optimize \
  -H 'content-type: application/json' \
  -d '{"priorities_dataset_id": "<processed-priorities-dataset-id>"}'

# Either can be combined with priority zones, whose weight multiplies
# whichever base weight was chosen:
curl -X POST localhost:8000/api/v1/analysis-runs/<viewshed-run-id>/optimize \
  -H 'content-type: application/json' \
  -d '{"preset": "valley_priority", "priority_zones": [{"geometry": {"type": "Polygon", "coordinates": [[[-3.75,40.39],[-3.74,40.39],[-3.74,40.40],[-3.75,40.40],[-3.75,40.39]]]}, "weight": 5.0}]}'
```

`priorities_dataset_id` and `preset` are mutually exclusive. Whatever was
used is recorded on the solution as `weights_summary` — `{"source": "preset",
"preset": "ridge_priority", ...}` or `{"source": "raster",
"priorities_dataset_id": ...}`, plus any zone multipliers — so a solution's
weighting is always reconstructible after the fact. `coverage_ratio`
(physical) and `weighted_coverage_ratio` are always both present, whichever
weighting was used.

## Configuration

Every API setting is read from the environment with the `SENTINEL_` prefix, or
from a `.env` file at the repository root. `.env` is git-ignored;
`.env.example` documents every variable. No secret ever lives in the repository.

Paths are never hardcoded: `app/core/paths.py` discovers the repository root
from marker files, and `SENTINEL_DATA_DIR` overrides the data location in
containers and in production.

## Repository layout

```text
apps/api                 FastAPI service
  app/api                HTTP routes (thin; no geospatial logic)
  app/core               config, logging, errors, paths, checksums
  app/db                 SQLAlchemy engine, session, base, entities
  app/geo                CRS selection, raster metadata, validation, warp (incl. grid alignment), terrain, candidates, viewshed
  app/optimization       solve_greedy, the candidate-cell matrix and cell-weight construction (no DB, no HTTP)
  app/schemas            Pydantic request/response models
  app/services           storage, projects, datasets, ingestion, candidates, viewsheds, optimization, priorities
  app/workers            standalone worker processes (viewshed_worker)
  migrations             Alembic
  tests                  pytest
apps/web                 Next.js frontend
packages/shared-schemas  OpenAPI document + generated TypeScript types
data/raw                 immutable uploaded datasets
data/processed           reprojected, clipped and derived rasters
data/outputs             analysis outputs: viewshed masks, packed bitsets, previews
docs/adr                 architecture decision records
scripts                  operational scripts (sample DEM, DEM download, OpenAPI export)
```

## API and frontend contract

`packages/shared-schemas/openapi.json` is exported from the FastAPI app, and
`src/generated/api.ts` is generated from it. Neither file is edited by hand.
After changing an API schema:

```bash
make schemas
git add packages/shared-schemas
```

CI fails when the committed files drift from the API.

## Sample data

No dataset is committed. Two options:

```bash
make sample-dem                                        # synthetic terrain, metric CRS
uv run --project apps/api python scripts/fetch_dem.py <url>   # a real DEM
```

The synthetic DEM is clearly marked (`source=synthetic` in the GeoTIFF tags)
and must never be presented as a real survey. See `docs/data-sources.md` for
public DEM providers.

## Conventions

- Python: type hints everywhere, mypy strict, Ruff, `pathlib`, structured logs,
  domain exceptions from `app.core.errors`.
- TypeScript: strict mode, no `any`, typed API client, components render data
  and never compute geospatial results.
- Geospatial: distances, buffers, slopes, areas and viewsheds are computed in a
  projected metric CRS only; units are explicit; every transformation is tested.
