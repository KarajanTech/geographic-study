"""Unit tests for app.optimization.weights — pure array functions, no I/O."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.errors import InvalidInputError
from app.optimization.weights import (
    PriorityZoneMask,
    apply_priority_zones,
    normalize_weights,
    preset_weights,
)


def test_normalize_weights_min_max() -> None:
    raw = np.array([0.0, 5.0, 10.0])
    result = normalize_weights(raw)
    assert result == pytest.approx([0.0, 0.5, 1.0])


def test_normalize_weights_constant_input_is_uniform() -> None:
    raw = np.array([7.0, 7.0, 7.0])
    result = normalize_weights(raw)
    assert result == pytest.approx([1.0, 1.0, 1.0])


def test_normalize_weights_empty_input() -> None:
    result = normalize_weights(np.array([]))
    assert result.size == 0


def test_normalize_weights_never_negative() -> None:
    raw = np.array([-10.0, 0.0, 10.0, 20.0])
    result = normalize_weights(raw)
    assert np.all(result >= 0.0)
    assert result == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])


def test_preset_uniform_ignores_elevation() -> None:
    elevation = np.array([100.0, 500.0, 900.0])
    result = preset_weights("uniform", elevation)
    assert result == pytest.approx([1.0, 1.0, 1.0])


def test_preset_ridge_priority_favours_higher_ground() -> None:
    elevation = np.array([100.0, 500.0, 900.0])
    result = preset_weights("ridge_priority", elevation)
    assert result[2] > result[1] > result[0]
    assert result == pytest.approx([0.0, 0.5, 1.0])


def test_preset_valley_priority_favours_lower_ground() -> None:
    elevation = np.array([100.0, 500.0, 900.0])
    result = preset_weights("valley_priority", elevation)
    assert result[0] > result[1] > result[2]
    assert result == pytest.approx([1.0, 0.5, 0.0])


def test_apply_priority_zones_boosts_only_zone_cells() -> None:
    weights = np.array([1.0, 1.0, 1.0, 1.0])
    zone = PriorityZoneMask(weight=3.0, mask=np.array([True, False, True, False]))

    result = apply_priority_zones(weights, [zone])

    assert result == pytest.approx([3.0, 1.0, 3.0, 1.0])


def test_apply_priority_zones_stacks_overlapping_zones() -> None:
    weights = np.ones(3)
    zone_a = PriorityZoneMask(weight=2.0, mask=np.array([True, True, False]))
    zone_b = PriorityZoneMask(weight=5.0, mask=np.array([False, True, True]))

    result = apply_priority_zones(weights, [zone_a, zone_b])

    # Cell 1 sits in both zones: multipliers compose rather than override.
    assert result == pytest.approx([2.0, 10.0, 5.0])


def test_apply_priority_zones_no_zones_is_a_no_op() -> None:
    weights = np.array([1.0, 2.0, 3.0])
    assert apply_priority_zones(weights, []) == pytest.approx(weights)


def test_apply_priority_zones_rejects_mismatched_mask_shape() -> None:
    weights = np.ones(4)
    zone = PriorityZoneMask(weight=2.0, mask=np.array([True, False, True]))

    with pytest.raises(InvalidInputError):
        apply_priority_zones(weights, [zone])
