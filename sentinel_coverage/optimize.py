"""Greedy max-coverage optimizer: pick the fewest/most effective Sentinel
mast positions to maximize weighted surveillance coverage. This is the
direct answer to "minimum poles for maximum area" -- the marginal-gain
history is the coverage-vs-N elbow curve.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class GreedyResult:
    selected_indices: list[int]
    marginal_gain_history: list[float]  # weighted area added at each step
    cumulative_coverage_frac_history: list[float]  # fraction of total weight covered so far
    covered_mask: np.ndarray


def greedy_max_coverage(
    candidate_masks: np.ndarray,  # (n_candidates, n_cells) bool
    cell_weights: np.ndarray,  # (n_cells,) float, e.g. cell_area_m2 * coverage_weight
    k: int | None = None,
    target_coverage: float | None = None,
    min_marginal_gain_frac: float | None = None,
) -> GreedyResult:
    """Standard greedy algorithm for the maximum-coverage problem: at each
    step, pick the candidate whose viewshed adds the most currently-
    uncovered weighted area, until a stopping condition is hit.

    Stopping modes (set at least one of k / target_coverage;
    min_marginal_gain_frac can combine with either):
    - k: stop after selecting exactly k candidates (or fewer if none add
      anything). Fixed-cardinality formulation -- greedy is a (1 - 1/e)
      approximation to the optimal k-mast solution here (Nemhauser-Wolsey-
      Fisher).
    - target_coverage: stop once cumulative covered weight reaches this
      fraction of the total weight achievable by the full candidate set.
      Minimum-set-cover formulation -- greedy is a ln(n)+1 approximation to
      the minimum number of masts here, a *different* guarantee than the
      fixed-k case above.
    - min_marginal_gain_frac: stop early once the best remaining candidate
      would add less than this fraction of total weight, even if k /
      target_coverage hasn't been reached (diminishing returns).
    """
    if k is None and target_coverage is None:
        raise ValueError("greedy_max_coverage needs at least one of k or target_coverage")

    n_candidates, n_cells = candidate_masks.shape
    total_weight = float(cell_weights.sum())
    achievable_weight = float(cell_weights[np.any(candidate_masks, axis=0)].sum())

    covered = np.zeros(n_cells, dtype=bool)
    remaining_mask = np.ones(n_candidates, dtype=bool)
    selected: list[int] = []
    marginal_gains: list[float] = []
    coverage_fracs: list[float] = []
    covered_weight = 0.0

    while remaining_mask.any():
        if k is not None and len(selected) >= k:
            break
        if (
            target_coverage is not None
            and achievable_weight > 0
            and covered_weight / achievable_weight >= target_coverage
        ):
            break

        uncovered_weight = np.where(covered, 0.0, cell_weights)
        gains = candidate_masks @ uncovered_weight  # (n_candidates,), vectorized mat-vec
        gains[~remaining_mask] = -1.0
        best_idx = int(np.argmax(gains))
        best_gain = float(gains[best_idx])

        if best_gain <= 0.0:
            break
        if (
            min_marginal_gain_frac is not None
            and total_weight > 0
            and (best_gain / total_weight) < min_marginal_gain_frac
        ):
            break

        covered |= candidate_masks[best_idx]
        covered_weight += best_gain
        selected.append(best_idx)
        marginal_gains.append(best_gain)
        coverage_fracs.append(covered_weight / total_weight if total_weight > 0 else 0.0)
        remaining_mask[best_idx] = False

    return GreedyResult(selected, marginal_gains, coverage_fracs, covered)
