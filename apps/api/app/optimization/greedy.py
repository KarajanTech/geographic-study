"""Greedy maximum coverage optimizer.

Given a set of candidate coverage masks over a shared cell universe, repeatedly
picks the candidate whose *marginal* gain — the weighted surface it covers
that nothing selected so far already covers — is largest, until a stopping
condition is met. This is the classic greedy algorithm for maximum coverage: it
has no exactness guarantee, but it is simple, fast, deterministic, and a
well-known (1 - 1/e) approximation of the optimum. ``ROADMAP.md`` requires it
before anything exact (CP-SAT, Phase 8) is attempted.

Pure function, no I/O: the caller supplies plain arrays and gets a plain
dataclass back. This is what lets it run synchronously inside an HTTP request,
be unit tested in isolation, and later be reused by a worker without change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from app.core.errors import InvalidInputError

ALGORITHM_VERSION = "greedy-max-coverage-v1"

CoverageMask = NDArray[np.bool_]


class GreedyStopReason(StrEnum):
    """Why the algorithm stopped selecting more candidates."""

    MAX_SITES_REACHED = "max_sites_reached"
    TARGET_COVERAGE_REACHED = "target_coverage_reached"
    NO_CANDIDATES_REMAINING = "no_candidates_remaining"
    NO_POSITIVE_GAIN = "no_positive_gain"
    NO_CANDIDATES_PROVIDED = "no_candidates_provided"


@dataclass(frozen=True, slots=True)
class GreedySolution:
    """Everything AGENT_INSTRUCTIONS.md's ``solve_greedy`` contract asks for."""

    selected_order: list[int] = field(default_factory=list)
    """Candidate indices, in the order the greedy algorithm picked them."""
    selected_indices: list[int] = field(default_factory=list)
    """The same set, sorted ascending — the final selection with no order."""
    marginal_gains: list[float] = field(default_factory=list)
    """Weighted gain contributed by each pick, aligned with ``selected_order``."""
    cumulative_coverage: list[float] = field(default_factory=list)
    """Unweighted fraction of cells covered after each pick, 0 to 1."""
    cumulative_weighted_coverage: list[float] = field(default_factory=list)
    """Weighted fraction of the universe covered after each pick, 0 to 1."""
    cumulative_cost: list[float] | None = None
    """Running total of ``candidate_costs`` for picks so far, if costs were given."""
    stop_reason: GreedyStopReason = GreedyStopReason.NO_CANDIDATES_PROVIDED
    runtime_seconds: float = 0.0
    total_cells: int = 0
    total_weight: float = 0.0

    @property
    def final_coverage(self) -> float:
        return self.cumulative_coverage[-1] if self.cumulative_coverage else 0.0

    @property
    def final_weighted_coverage(self) -> float:
        return self.cumulative_weighted_coverage[-1] if self.cumulative_weighted_coverage else 0.0


def _validate_inputs(
    candidate_masks: list[CoverageMask],
    cell_weights: NDArray[np.floating],
    max_sites: int | None,
    target_coverage: float | None,
    candidate_costs: NDArray[np.floating] | None,
) -> None:
    n_cells = cell_weights.shape[0]
    if cell_weights.ndim != 1:
        msg = "cell_weights must be one-dimensional"
        raise InvalidInputError(msg, details={"shape": cell_weights.shape})
    if np.any(cell_weights < 0):
        msg = "cell_weights must be non-negative"
        raise InvalidInputError(msg)
    for i, mask in enumerate(candidate_masks):
        if mask.shape != (n_cells,):
            msg = "Every candidate mask must match the shape of cell_weights"
            raise InvalidInputError(
                msg, details={"candidate_index": i, "mask_shape": mask.shape, "n_cells": n_cells}
            )
    if max_sites is not None and max_sites < 1:
        msg = "max_sites must be at least 1"
        raise InvalidInputError(msg, details={"max_sites": max_sites})
    if target_coverage is not None and not 0.0 < target_coverage <= 1.0:
        msg = "target_coverage must be between 0 (exclusive) and 1 (inclusive)"
        raise InvalidInputError(msg, details={"target_coverage": target_coverage})
    if candidate_costs is not None and candidate_costs.shape != (len(candidate_masks),):
        msg = "candidate_costs must have one entry per candidate mask"
        raise InvalidInputError(
            msg,
            details={
                "candidate_costs_shape": candidate_costs.shape,
                "candidate_count": len(candidate_masks),
            },
        )


def solve_greedy(
    candidate_masks: list[CoverageMask],
    cell_weights: NDArray[np.floating],
    max_sites: int | None,
    target_coverage: float | None,
    candidate_costs: NDArray[np.floating] | None = None,
) -> GreedySolution:
    """Greedily select candidates to maximize weighted coverage.

    Args:
        candidate_masks: One boolean array per candidate, all the same shape
            as ``cell_weights`` — ``True`` where that candidate sees the cell.
        cell_weights: Non-negative weight per cell. Uniform (all 1.0) for
            Phase 4; risk-weighted values arrive in Phase 6.
        max_sites: Stop once this many candidates are selected. ``None`` for
            no limit.
        target_coverage: Stop once weighted coverage reaches this fraction
            (0, 1]. ``None`` for no target.
        candidate_costs: Per-candidate cost, tracked as a running total in the
            result but not (yet) used to influence selection — Phase 7 adds
            budget-constrained optimization; this parameter exists now so that
            phase does not need to change this function's signature.

    Raises:
        InvalidInputError: on shape mismatches or out-of-range parameters.

    The result's ``cumulative_coverage`` and ``cumulative_weighted_coverage``
    are non-decreasing by construction — a candidate is only ever added, never
    removed, and each addition can only grow the covered set.
    """
    _validate_inputs(candidate_masks, cell_weights, max_sites, target_coverage, candidate_costs)

    n_cells = cell_weights.shape[0]
    total_weight = float(cell_weights.sum())
    started = time.perf_counter()

    if not candidate_masks or total_weight <= 0.0:
        return GreedySolution(
            stop_reason=GreedyStopReason.NO_CANDIDATES_PROVIDED,
            runtime_seconds=time.perf_counter() - started,
            total_cells=n_cells,
            total_weight=total_weight,
        )

    covered = np.zeros(n_cells, dtype=bool)
    remaining = set(range(len(candidate_masks)))

    selected_order: list[int] = []
    marginal_gains: list[float] = []
    cumulative_coverage: list[float] = []
    cumulative_weighted_coverage: list[float] = []
    cumulative_cost: list[float] | None = [] if candidate_costs is not None else None
    running_cost = 0.0

    stop_reason = GreedyStopReason.NO_CANDIDATES_REMAINING
    while True:
        if max_sites is not None and len(selected_order) >= max_sites:
            stop_reason = GreedyStopReason.MAX_SITES_REACHED
            break
        if not remaining:
            stop_reason = GreedyStopReason.NO_CANDIDATES_REMAINING
            break

        # Sorted so ties are broken by the lowest candidate index — the
        # ranking Phase 2 already produced (best sites first) — making the
        # result fully reproducible.
        remaining_indices = sorted(remaining)
        uncovered_gain = (
            np.stack([candidate_masks[i] & ~covered for i in remaining_indices]) @ cell_weights
        )
        best_position = int(np.argmax(uncovered_gain))
        best_gain = float(uncovered_gain[best_position])
        best_index = remaining_indices[best_position]

        if best_gain <= 0.0:
            stop_reason = GreedyStopReason.NO_POSITIVE_GAIN
            break

        covered |= candidate_masks[best_index]
        remaining.discard(best_index)
        selected_order.append(best_index)
        marginal_gains.append(best_gain)
        cumulative_coverage.append(float(covered.sum()) / n_cells)
        cumulative_weighted_coverage.append(float(covered @ cell_weights) / total_weight)
        if candidate_costs is not None and cumulative_cost is not None:
            running_cost += float(candidate_costs[best_index])
            cumulative_cost.append(running_cost)

        if target_coverage is not None and cumulative_weighted_coverage[-1] >= target_coverage:
            stop_reason = GreedyStopReason.TARGET_COVERAGE_REACHED
            break

    return GreedySolution(
        selected_order=selected_order,
        selected_indices=sorted(selected_order),
        marginal_gains=marginal_gains,
        cumulative_coverage=cumulative_coverage,
        cumulative_weighted_coverage=cumulative_weighted_coverage,
        cumulative_cost=cumulative_cost,
        stop_reason=stop_reason,
        runtime_seconds=time.perf_counter() - started,
        total_cells=n_cells,
        total_weight=total_weight,
    )
