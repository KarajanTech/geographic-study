# ADR 0007: Greedy maximum-coverage optimizer

- Status: accepted
- Date: 2026-07-25
- Phase: 4
- Extends: [ADR 0005](0005-candidate-generation.md), [ADR 0006](0006-viewshed-engine-and-worker.md)

## Context

Phase 3 leaves each candidate with its own viewshed: which cells of the
terrain it sees. Phase 4 answers the actual question a Sentinel Planner user
has — which subset of those candidates, placed together, sees the most
ground? `AGENT_INSTRUCTIONS.md` mandates a specific `solve_greedy` signature,
keeping the optimizer independent of the HTTP API and the database (a plain
function over arrays, not a service), and forbids ML — this is a classic
submodular maximum-coverage problem, not a learning problem.

## Decisions

### Greedy maximum coverage, not an exact solver, for Phase 4

Maximum coverage is NP-hard in general, but the greedy algorithm — repeatedly
pick the candidate whose still-uncovered contribution is largest — has a
provable (1 − 1/e) ≈ 63% approximation guarantee, is deterministic given a
fixed tie-break, and runs in time proportional to `candidates × cells`, not
exponential in either. `ARCHITECTURE.md`'s Phase 8 already reserves the exact
formulation (CP-SAT/ILP) for later, once budget constraints and redundancy
targets exist to justify the extra machinery. `solve_greedy` is written so
that reservation costs nothing today: `OptimizationSolution.solver` records
which solver produced a row, and nothing about the schema or the API assumes
greedy is the only one that ever will.

### The candidate-cell matrix is built by exact grid embedding, not reprojection

Each viewshed from Phase 3 is a boolean mask cropped to a small bounding box
around its own observer — a different extent per candidate — so they cannot
be combined directly. Combining them requires one shared cell-index space.

`LineOfSightViewshedEngine.compute` (ADR 0006) builds every viewshed's
`sub_transform` as `transform * Affine.translation(col_min, row_min)`, where
`col_min`/`row_min` are integers. This means every viewshed mask is
grid-aligned with the source surface at a whole-pixel offset — never
resampled, never rotated. `app.optimization.matrix.build_candidate_cell_matrix`
exploits this directly: it inverse-transforms each viewshed's stored
`(bounds_left, bounds_top)` back to a `(col, row)` offset, checks the result is
an integer within `1e-6` (catching any future engine that violates the
assumption instead of silently misaligning coverage), and places the local
mask into a full-surface boolean array with plain NumPy slicing. This is
exact, not an approximation, and orders of magnitude cheaper than resampling
every mask through `rasterio.warp`.

Nodata cells are excluded from the shared index (`valid_flat_index`) so the
optimizer never rewards a candidate for "seeing" a cell the DEM never actually
described.

### Optimization runs synchronously, unlike viewshed computation

ADR 0006 requires viewsheds to run in a worker because ray casting per
candidate is comparatively expensive and the roadmap explicitly asks for
async execution there. The greedy optimizer's inner loop is dense boolean
array arithmetic (`(mask & ~covered) @ weights`) over already-computed masks —
milliseconds to low seconds even at hundreds of candidates — so queuing it
through the same `pending`/worker-poll machinery would add latency and
complexity for no benefit. `POST /analysis-runs/{id}/optimize` computes the
solution and returns it in the same request, creating its `AnalysisRun`
already `completed`. If a future solver (CP-SAT on thousands of candidates) is
slow enough to need a worker, it can reuse the existing queue pattern without
changing this endpoint's contract — the response shape does not depend on how
it was produced.

### `candidate_costs`, `total_cost`, and `redundancy_metrics` are accepted or stored, not yet used

`solve_greedy`'s mandated signature includes `candidate_costs`; Phase 4 tracks
it as a running total (`GreedySolution.cumulative_cost`) but the selection
rule itself is uniform-cost maximum coverage — cost does not influence which
candidate is picked next. Budget-constrained selection (cost-per-marginal-cell
ratios, a budget cutoff) is Phase 7's scope in `ARCHITECTURE.md`, and
implementing it now would mean guessing at a cost model the roadmap has not
specified yet. `OptimizationSolution.total_cost` and `.redundancy_metrics`
exist as nullable columns today for the same reason `Viewshed` gained its
`bitset_uri` column ahead of the optimizer that needed it: adding the column
now avoids a second migration later, but nothing populates it until its own
phase (7 for cost, 8 for redundancy) defines what it means.

### Deterministic tie-breaking by ascending candidate index

When two candidates offer identical marginal gain, `solve_greedy` picks the
lower index. Combined with the deterministic candidate ordering from Phase 2
(ADR 0005) and the exact grid embedding above, this makes a run fully
reproducible from `(candidate_masks, cell_weights, max_sites,
target_coverage, candidate_costs)` alone — the same non-negotiable
reproducibility rule applied throughout this project, no seed needed since
nothing here is randomized.

## Consequences

- Adding hundreds of candidates costs a few seconds of NumPy array ops, not
  minutes of ray casting — verified by `test_greedy_optimizer.py`'s
  300-candidate/50,000-cell case.
- The optimizer module has zero imports from `app.db` or `app.api`; it is
  tested and could be reused by a worker or a CLI without touching a request
  handler.
- The frontend's units-vs-coverage curve (`OptimizationTable`) and the
  selected-candidates map overlay both read directly from
  `OptimizationSolution.iterations`, which is exactly `solve_greedy`'s
  per-step trace — no client-side recomputation of coverage.
- Phase 7 (budget-constrained selection) and Phase 8 (exact/CP-SAT solving,
  redundancy metrics) extend this module and its schema without breaking it:
  the reserved-but-unused fields and the `solver` column are already in place.
