"""Tests for backend/app/utils/geo.py — haversine + proximity helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CACHE_DIR", str(ROOT / ".test_cache"))

from app.utils.geo import haversine_m, within_m


def test_distance_zero() -> None:
    assert haversine_m(40.7128, -74.0060, 40.7128, -74.0060) == 0.0


def test_distance_nyc_to_la_approx() -> None:
    # NYC to LA ≈ 3,940 km. Allow ±2 % spherical-vs-ellipsoid drift.
    d = haversine_m(40.7128, -74.0060, 34.0522, -118.2437)
    assert d is not None
    assert 3_860_000 < d < 4_020_000


def test_within_50m_true() -> None:
    # ~0.0003° lat ≈ 33 m
    assert within_m(40.0, -73.0, 40.0003, -73.0, threshold_m=50.0)


def test_within_50m_false_when_apart() -> None:
    assert not within_m(40.0, -73.0, 40.01, -73.0, threshold_m=50.0)


def test_missing_coords_yield_none_distance() -> None:
    assert haversine_m(None, -73.0, 40.0, -73.0) is None
    assert haversine_m(40.0, None, 40.0, -73.0) is None


def test_within_returns_false_when_unknown() -> None:
    assert not within_m(None, None, 40.0, -73.0, threshold_m=50.0)
