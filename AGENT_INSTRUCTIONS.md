# Instructions for Codex or Claude Code

You are implementing Sentinel Planner, a geospatial application that determines the optimal placement of wildfire surveillance towers.

Read these files before making changes:

1. `README.md`
2. `PRODUCT_SPEC.md`
3. `ARCHITECTURE.md`
4. `ROADMAP.md`

## Working method

Work on one roadmap phase at a time.

Before coding:

1. inspect the repository;
2. identify the current phase;
3. list affected files;
4. state assumptions;
5. propose a short implementation plan.

Then implement the phase completely.

After coding:

1. run formatting;
2. run lint;
3. run type checks;
4. run tests;
5. report failures honestly;
6. update documentation;
7. summarize files changed;
8. state which acceptance criteria are satisfied.

## Non-negotiable rules

- Do not implement later roadmap phases prematurely.
- Do not introduce machine learning unless explicitly requested.
- Do not use latitude and longitude directly for metric distance calculations.
- Preserve CRS information through all geospatial transformations.
- Never silently assume units.
- Never overwrite raw uploaded datasets.
- Every analysis must be reproducible.
- Every analysis must store its parameters and algorithm version.
- Prefer deterministic algorithms.
- Use random seeds where randomness exists.
- Validate all geospatial inputs.
- Add tests for every important geospatial transformation.
- Keep the optimization engine independent from the HTTP API.
- Keep the viewshed engine behind an interface.
- Avoid unnecessary microservices.
- Avoid frontend-only calculations for scientific results.
- Avoid hardcoded local paths.
- Avoid fake production data.

## Coding standards

### Python

- Python 3.12
- type hints required;
- Pydantic for API schemas;
- SQLAlchemy 2 style;
- pytest;
- Ruff;
- mypy;
- pathlib instead of raw path strings;
- structured logging;
- clear domain exceptions.

### TypeScript

- strict mode;
- no `any` unless justified;
- typed API client;
- components should not contain geospatial business logic;
- map layers should use explicit source and layer identifiers.

## Geospatial standards

For every raster or vector dataset, track:

- CRS;
- bounds;
- resolution;
- nodata;
- units;
- checksum;
- source;
- processing history.

Before any distance, buffer, slope, area or viewshed calculation:

- ensure the dataset uses a projected metric CRS;
- document the CRS selected;
- test the transformation.

## Performance rules

- do not calculate all viewsheds inside an HTTP request;
- use worker tasks;
- cache repeated viewsheds;
- store compact masks;
- avoid loading all rasters into memory without bounds;
- profile before optimizing;
- prefer NumPy vectorization over Python loops.

## Optimization rules

The first optimizer must be greedy maximum coverage.

It must expose a pure function with inputs similar to:

```python
def solve_greedy(
    candidate_masks: list[CoverageMask],
    cell_weights: NDArray,
    max_sites: int | None,
    target_coverage: float | None,
    candidate_costs: NDArray | None = None,
) -> GreedySolution:
    ...
```

The output must include:

- selected candidate indices;
- selected order;
- marginal gain at each iteration;
- cumulative coverage;
- weighted coverage;
- stop reason;
- runtime.

Do not add CP-SAT before the greedy optimizer is tested.

## Viewshed rules

The viewshed implementation must be wrapped behind an interface so GDAL can later be replaced or compared.

A viewshed cache key must include:

- source surface checksum;
- observer coordinates;
- observer height;
- target height;
- maximum distance;
- CRS;
- algorithm settings.

## Definition of done

A roadmap phase is complete only when:

- code works locally;
- tests pass;
- types pass;
- documentation is updated;
- acceptance criteria are demonstrated;
- no critical TODO is left hidden.

## Initial task

Start with Phase 0 from `ROADMAP.md`.

Create the repository foundation only. Do not implement viewshed or optimization yet.

At the end, provide:

1. repository tree;
2. commands to run locally;
3. test results;
4. acceptance criteria checklist;
5. recommended next task.
