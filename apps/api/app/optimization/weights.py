"""Cell-weight construction for risk-weighted coverage.

Pure functions over arrays, no I/O and no database — same discipline as
``greedy.py``. ``app.services.optimization`` reads whatever files or
geometries a request references and hands this module plain arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, assert_never, get_args

import numpy as np
from numpy.typing import NDArray

from app.core.errors import InvalidInputError

WeightPreset = Literal["uniform", "ridge_priority", "valley_priority"]
PRESET_NAMES: tuple[WeightPreset, ...] = get_args(WeightPreset)


@dataclass(frozen=True, slots=True)
class PriorityZoneMask:
    """A priority zone already rasterized onto the valid-cell universe."""

    weight: float
    mask: NDArray[np.bool_]


def normalize_weights(raw: NDArray[np.floating]) -> NDArray[np.float64]:
    """Min-max normalize to ``[0, 1]``.

    A constant input (every cell identical, including the degenerate
    zero-size case) becomes uniform ``1.0``s rather than dividing by zero —
    there is no meaningful relative priority to express when nothing varies.
    """
    values = raw.astype(np.float64)
    if values.size == 0:
        return values
    spread = float(values.max()) - float(values.min())
    if spread <= 0.0:
        return np.ones_like(values)
    return (values - float(values.min())) / spread


def preset_weights(preset: WeightPreset, elevation: NDArray[np.floating]) -> NDArray[np.float64]:
    """Terrain-derived illustrative weight presets.

    These are simple, transparent proxies computed only from the elevation
    this project already has — not a real wildfire-risk model. There is no
    vegetation, climate or ignition-history data in this system to ground one
    in, and inventing such data would violate "avoid fake production data".
    They exist so a preset can demonstrably change which cells matter (and
    therefore the optimizer's solution), per ``ROADMAP.md`` Phase 6, without
    requiring a raster upload.

    ``"uniform"`` is every cell weighted equally (Phase 4's behaviour).
    ``"ridge_priority"`` favours higher ground; ``"valley_priority"`` favours
    lower ground — opposite ends of the same normalized elevation.
    """
    if preset == "uniform":
        return np.ones(elevation.shape, dtype=np.float64)
    normalized = normalize_weights(elevation)
    if preset == "ridge_priority":
        return normalized
    if preset == "valley_priority":
        return 1.0 - normalized
    assert_never(preset)


def apply_priority_zones(
    weights: NDArray[np.float64], zones: list[PriorityZoneMask]
) -> NDArray[np.float64]:
    """Multiply each zone's cells by its own weight, on top of the base weights.

    Zones are not renormalized afterwards: the optimizer and the reported
    weighted-coverage ratio both divide by the weights' own sum, so a zone
    multiplier changes cells' weight *relative to the rest of the surface*
    regardless of the base weights' absolute scale.
    """
    result = weights.copy()
    for zone in zones:
        if zone.mask.shape != weights.shape:
            msg = "Priority zone mask must match the cell-weight universe"
            raise InvalidInputError(
                msg, details={"mask_shape": zone.mask.shape, "weights_shape": weights.shape}
            )
        result[zone.mask] *= zone.weight
    return result
