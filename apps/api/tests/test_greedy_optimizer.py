"""Greedy maximum coverage optimizer: the roadmap's critical acceptance tests."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.errors import InvalidInputError
from app.optimization.greedy import GreedyStopReason, solve_greedy


def _mask(n: int, *ranges: tuple[int, int]) -> np.ndarray:
    array = np.zeros(n, dtype=bool)
    for start, end in ranges:
        array[start:end] = True
    return array


def test_greedy_picks_the_largest_gain_first() -> None:
    """'A' covers half the cells, 'B' a third, 'C' barely any — A goes first."""
    n = 12
    a = _mask(n, (0, 6))
    b = _mask(n, (6, 10))
    c = _mask(n, (10, 11))
    weights = np.ones(n)

    solution = solve_greedy([a, b, c], weights, max_sites=None, target_coverage=None)

    assert solution.selected_order == [0, 1, 2]
    assert solution.marginal_gains == [6.0, 4.0, 1.0]


def test_cumulative_coverage_never_decreases() -> None:
    """'la cobertura acumulada nunca disminuye'."""
    rng = np.random.default_rng(7)
    n_cells, n_candidates = 500, 40
    masks = [rng.random(n_cells) > 0.85 for _ in range(n_candidates)]
    weights = np.ones(n_cells)

    solution = solve_greedy(masks, weights, max_sites=None, target_coverage=None)

    assert solution.cumulative_coverage == sorted(solution.cumulative_coverage)
    assert solution.cumulative_weighted_coverage == sorted(solution.cumulative_weighted_coverage)
    diffs = np.diff([0.0, *solution.cumulative_coverage])
    assert np.all(diffs >= -1e-12)


def test_no_candidate_is_selected_twice() -> None:
    """'ningún candidato se selecciona dos veces'."""
    rng = np.random.default_rng(3)
    n_cells, n_candidates = 300, 25
    masks = [rng.random(n_cells) > 0.7 for _ in range(n_candidates)]
    weights = np.ones(n_cells)

    solution = solve_greedy(masks, weights, max_sites=None, target_coverage=None)

    assert len(solution.selected_order) == len(set(solution.selected_order))
    assert solution.selected_indices == sorted(set(solution.selected_order))


def test_a_cell_covered_by_two_selected_candidates_only_counts_once() -> None:
    n = 10
    a = _mask(n, (0, 6))
    b = _mask(n, (4, 10))  # overlaps a on cells 4-5
    weights = np.ones(n)

    solution = solve_greedy([a, b], weights, max_sites=None, target_coverage=None)

    assert solution.selected_order == [0, 1]
    assert solution.marginal_gains == [6.0, 4.0]  # b only gains the 4 new cells
    assert solution.final_coverage == pytest.approx(1.0)


def test_stops_at_max_sites() -> None:
    n = 20
    masks = [_mask(n, (i, i + 3)) for i in range(0, 15, 3)]
    weights = np.ones(n)

    solution = solve_greedy(masks, weights, max_sites=2, target_coverage=None)

    assert len(solution.selected_order) == 2
    assert solution.stop_reason == GreedyStopReason.MAX_SITES_REACHED


def test_stops_at_target_coverage() -> None:
    n = 10
    a = _mask(n, (0, 5))
    b = _mask(n, (5, 10))
    weights = np.ones(n)

    solution = solve_greedy([a, b], weights, max_sites=None, target_coverage=0.5)

    assert solution.selected_order == [0]
    assert solution.stop_reason == GreedyStopReason.TARGET_COVERAGE_REACHED
    assert solution.final_weighted_coverage >= 0.5


def test_stops_when_no_positive_gain_remains() -> None:
    n = 10
    a = _mask(n, (0, 10))  # covers everything
    b = _mask(n, (2, 5))  # fully redundant once a is picked

    solution = solve_greedy([a, b], np.ones(n), max_sites=None, target_coverage=None)

    assert solution.selected_order == [0]
    assert solution.stop_reason == GreedyStopReason.NO_POSITIVE_GAIN


def test_stops_when_candidates_are_exhausted() -> None:
    n = 10
    a = _mask(n, (0, 4))
    b = _mask(n, (4, 8))

    solution = solve_greedy([a, b], np.ones(n), max_sites=None, target_coverage=None)

    assert solution.selected_order == [0, 1]
    assert solution.stop_reason == GreedyStopReason.NO_CANDIDATES_REMAINING


def test_no_candidates_provided_is_handled_gracefully() -> None:
    solution = solve_greedy([], np.ones(5), max_sites=None, target_coverage=None)

    assert solution.selected_order == []
    assert solution.stop_reason == GreedyStopReason.NO_CANDIDATES_PROVIDED
    assert solution.final_coverage == 0.0


def test_zero_total_weight_is_handled_gracefully() -> None:
    n = 5
    solution = solve_greedy([_mask(n, (0, n))], np.zeros(n), max_sites=None, target_coverage=None)

    assert solution.selected_order == []
    assert solution.stop_reason == GreedyStopReason.NO_CANDIDATES_PROVIDED


def test_results_are_reproducible() -> None:
    """'los resultados son reproducibles'."""
    rng = np.random.default_rng(11)
    n_cells, n_candidates = 400, 30
    masks = [rng.random(n_cells) > 0.8 for _ in range(n_candidates)]
    weights = np.ones(n_cells)

    first = solve_greedy(masks, weights, max_sites=None, target_coverage=None)
    second = solve_greedy(masks, weights, max_sites=None, target_coverage=None)

    assert first.selected_order == second.selected_order
    assert first.marginal_gains == second.marginal_gains
    assert first.cumulative_coverage == second.cumulative_coverage


def test_ties_are_broken_by_lowest_candidate_index() -> None:
    """Two candidates with identical, non-overlapping coverage: index 0 wins."""
    n = 10
    a = _mask(n, (0, 3))
    b = _mask(n, (3, 6))  # same size as a, no overlap — an exact tie

    solution = solve_greedy([a, b], np.ones(n), max_sites=1, target_coverage=None)

    assert solution.selected_order == [0]


def test_solves_a_demonstration_zone_with_hundreds_of_candidates() -> None:
    """'se puede resolver una zona de demostración con cientos de candidatos'."""
    rng = np.random.default_rng(42)
    n_cells, n_candidates = 50_000, 300
    masks = [rng.random(n_cells) > 0.97 for _ in range(n_candidates)]  # ~3% coverage each
    weights = np.ones(n_cells)

    solution = solve_greedy(masks, weights, max_sites=50, target_coverage=None)

    assert len(solution.selected_order) == 50
    assert solution.stop_reason == GreedyStopReason.MAX_SITES_REACHED
    assert solution.runtime_seconds < 30.0


def test_weighted_coverage_prefers_high_weight_cells() -> None:
    n = 10
    a = _mask(n, (0, 5))  # low-weight half
    b = _mask(n, (5, 10))  # high-weight half
    weights = np.array([1.0] * 5 + [10.0] * 5)

    solution = solve_greedy([a, b], weights, max_sites=1, target_coverage=None)

    assert solution.selected_order == [1]  # b covers 50 of weight vs a's 5


def test_candidate_costs_are_tracked_but_do_not_change_selection() -> None:
    n = 10
    a = _mask(n, (0, 6))
    b = _mask(n, (6, 10))
    costs = np.array([100.0, 1.0])  # a is far more expensive but still covers more

    solution = solve_greedy(
        [a, b], np.ones(n), max_sites=None, target_coverage=None, candidate_costs=costs
    )

    assert solution.selected_order == [0, 1]  # unaffected by cost
    assert solution.cumulative_cost == [100.0, 101.0]


def test_mismatched_mask_shape_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        solve_greedy([np.ones(5, dtype=bool)], np.ones(10), max_sites=None, target_coverage=None)


def test_negative_cell_weights_are_rejected() -> None:
    with pytest.raises(InvalidInputError):
        solve_greedy(
            [np.ones(5, dtype=bool)],
            np.array([-1.0, 1, 1, 1, 1]),
            max_sites=None,
            target_coverage=None,
        )


@pytest.mark.parametrize("max_sites", [0, -1])
def test_non_positive_max_sites_is_rejected(max_sites: int) -> None:
    with pytest.raises(InvalidInputError):
        solve_greedy(
            [np.ones(5, dtype=bool)], np.ones(5), max_sites=max_sites, target_coverage=None
        )


@pytest.mark.parametrize("target_coverage", [0.0, -0.1, 1.1])
def test_out_of_range_target_coverage_is_rejected(target_coverage: float) -> None:
    with pytest.raises(InvalidInputError):
        solve_greedy(
            [np.ones(5, dtype=bool)], np.ones(5), max_sites=None, target_coverage=target_coverage
        )


def test_mismatched_candidate_costs_length_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        solve_greedy(
            [np.ones(5, dtype=bool), np.ones(5, dtype=bool)],
            np.ones(5),
            max_sites=None,
            target_coverage=None,
            candidate_costs=np.array([1.0]),
        )
