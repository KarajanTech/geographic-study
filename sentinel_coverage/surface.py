"""Combine bare-earth elevation with canopy height into an obstruction surface.

Kept as its own tiny module so the split is explicit and hard to miss: the
*obstruction* surface (what blocks a line of sight) includes canopy, but the
*target* being tested for visibility is always measured against bare earth
plus a target height offset -- never against this surface. Conflating the
two would silently double-count canopy height. See viewshed.py.
"""
from __future__ import annotations

import numpy as np


def build_surface_model(bare_earth_m: np.ndarray, canopy_height_m: np.ndarray) -> np.ndarray:
    return bare_earth_m + canopy_height_m
