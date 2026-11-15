"""Offline unit tests for US state point-in-polygon assignment and trend ranking aggregation."""
from __future__ import annotations

import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from fetch_data import END, START  # noqa: E402
from rank_us_states import (  # noqa: E402
    aggregate_state_metrics,
    assign_cells_to_states,
    cmip6_box_cell_count,
    compute_cell_trends,
    point_in_polygon,
    point_in_ring,
    rank_temperature_states,
)


def test_point_in_ring_and_polygon_with_hole():
    outer = [[-100.0, 30.0], [-90.0, 30.0], [-90.0, 40.0], [-100.0, 40.0], [-100.0, 30.0]]
    hole = [[-96.0, 34.0], [-94.0, 34.0], [-94.0, 36.0], [-96.0, 36.0], [-96.0, 34.0]]
    poly_geom = {"type": "Polygon", "coordinates": [outer, hole]}

    assert point_in_ring(-95.0, 35.0, outer) is True
    assert point_in_ring(-85.0, 35.0, outer) is False
    # Point inside outer ring but inside the hole must be excluded
    assert point_in_polygon(-95.0, 35.0, poly_geom) is False
    # Point inside outer ring and outside hole is included
    assert point_in_polygon(-92.0, 32.0, poly_geom) is True
    assert point_in_polygon(-105.0, 35.0, poly_geom) is False


def test_point_in_multipolygon_and_state_assignment():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"STUSPS": "AA", "NAME": "Alpha"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-110.0, 35.0], [-105.0, 35.0], [-105.0, 40.0], [-110.0, 40.0], [-110.0, 35.0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"STUSPS": "BB", "NAME": "Beta"},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[-100.0, 30.0], [-98.0, 30.0], [-98.0, 32.0], [-100.0, 32.0], [-100.0, 30.0]]],
                        [[[-97.0, 30.0], [-95.0, 30.0], [-95.0, 32.0], [-97.0, 32.0], [-97.0, 30.0]]],
                    ],
                },
            },
        ],
    }
    cells = [
        {"lat": 37.5, "lon": -107.5},  # AA
        {"lat": 31.0, "lon": -99.0},   # BB (first island)
        {"lat": 31.0, "lon": -96.0},   # BB (second island)
        {"lat": 25.0, "lon": -80.0},   # None (ocean / outside)
    ]
    assigned, names = assign_cells_to_states(cells, geojson)
    assert assigned == ["AA", "BB", "BB", None]
    assert names == {"AA": "Alpha", "BB": "Beta"}


def test_aggregate_state_metrics_and_ranking():
    state_names = {"TX": "Texas", "ME": "Maine", "WY": "Wyoming", "RI": "Rhode Island"}
    records = [
        # RI has only 2 cells -> must be dropped (< 4 cells)
        {"state": "RI", "param": "T2M", "season": "JJA", "slope_per_decade": 0.4, "p": 0.001, "significant_fdr": 1},
        {"state": "RI", "param": "T2M", "season": "JJA", "slope_per_decade": 0.5, "p": 0.001, "significant_fdr": 1},
        # ME: 4 cells, all 4 significant and positive -> share=1.0, consistency=1.0, clarity=1.0
        {"state": "ME", "param": "T2M", "season": "JJA", "slope_per_decade": 0.30, "p": 0.001, "significant_fdr": 1},
        {"state": "ME", "param": "T2M", "season": "JJA", "slope_per_decade": 0.40, "p": 0.002, "significant_fdr": 1},
        {"state": "ME", "param": "T2M", "season": "JJA", "slope_per_decade": 0.50, "p": 0.001, "significant_fdr": 1},
        {"state": "ME", "param": "T2M", "season": "JJA", "slope_per_decade": 0.60, "p": 0.003, "significant_fdr": 1},
        # TX: 4 cells, 3 significant (2 positive, 1 negative) -> share=0.75, consistency=2/3, clarity=0.5
        {"state": "TX", "param": "T2M", "season": "JJA", "slope_per_decade": 0.40, "p": 0.001, "significant_fdr": 1},
        {"state": "TX", "param": "T2M", "season": "JJA", "slope_per_decade": 0.20, "p": 0.004, "significant_fdr": 1},
        {"state": "TX", "param": "T2M", "season": "JJA", "slope_per_decade": -0.30, "p": 0.002, "significant_fdr": 1},
        {"state": "TX", "param": "T2M", "season": "JJA", "slope_per_decade": 0.05, "p": 0.400, "significant_fdr": 0},
        # WY: 4 cells, 0 significant -> null example
        {"state": "WY", "param": "T2M", "season": "JJA", "slope_per_decade": 0.10, "p": 0.250, "significant_fdr": 0},
        {"state": "WY", "param": "T2M", "season": "JJA", "slope_per_decade": -0.05, "p": 0.600, "significant_fdr": 0},
        {"state": "WY", "param": "T2M", "season": "JJA", "slope_per_decade": 0.02, "p": 0.800, "significant_fdr": 0},
        {"state": "WY", "param": "T2M", "season": "JJA", "slope_per_decade": 0.08, "p": 0.300, "significant_fdr": 0},
    ]

    rows = aggregate_state_metrics(records, state_names, min_cells=4)
    by_state = {r["state"]: r for r in rows}

    assert "RI" not in by_state
    assert set(by_state) == {"ME", "TX", "WY"}

    me = by_state["ME"]
    assert me["n_cells"] == 4
    assert me["share_sig_fdr"] == pytest.approx(1.0)
    assert me["consistency"] == pytest.approx(1.0)
    assert me["clarity_score"] == pytest.approx(1.0)
    assert me["median_slope_sig"] == pytest.approx(0.45)
    assert me["median_slope_all"] == pytest.approx(0.45)

    tx = by_state["TX"]
    assert tx["n_cells"] == 4
    assert tx["share_sig_fdr"] == pytest.approx(0.75)
    assert tx["consistency"] == pytest.approx(2.0 / 3.0, rel=1e-5)
    assert tx["clarity_score"] == pytest.approx(0.5, rel=1e-5)
    assert tx["median_slope_sig"] == pytest.approx(0.20)
    assert tx["median_slope_all"] == pytest.approx(0.125)

    wy = by_state["WY"]
    assert wy["n_sig_fdr"] == 0
    assert wy["share_sig_fdr"] == 0.0
    assert wy["consistency"] == 0.0
    assert wy["clarity_score"] == 0.0
    assert wy["median_slope_sig"] is None
    assert wy["median_slope_all"] == pytest.approx(0.05)

    ranked = rank_temperature_states(rows)
    assert [r["state"] for r in ranked] == ["ME", "TX", "WY"]


def test_cmip6_box_cell_count():
    # Ukraine+Poland reference box: 9x21 deg at 0.25 deg = 37x85 = 3145 cells
    n_lat, n_lon, total = cmip6_box_cell_count(44.0, 22.0, 53.0, 43.0, step=0.25)
    assert (n_lat, n_lon, total) == (37, 85, 3145)


def test_compute_cell_trends_and_ranking_without_network():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"STUSPS": "AA", "NAME": "Alpha"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-110.0, 35.0], [-105.0, 35.0], [-105.0, 40.0], [-110.0, 40.0], [-110.0, 35.0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"STUSPS": "BB", "NAME": "Beta"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-100.0, 30.0], [-95.0, 30.0], [-95.0, 35.0], [-100.0, 35.0], [-100.0, 30.0]]],
                },
            },
        ],
    }

    n_months = (END - START + 1) * 12

    def make_monthly(slope_per_year: float, amp: float, phase: int) -> list[float]:
        return [
            round(10.0 + slope_per_year * (i // 12) + amp * math.sin(1.7 * (i // 12) + phase) + 5.0 * math.sin(2.0 * math.pi * (i % 12) / 12.0), 4)
            for i in range(n_months)
        ]

    short_monthly: list[float | None] = [None] * (n_months - 10 * 12) + make_monthly(0.0, 0.2, 0)[-(10 * 12):]
    cells = [
        {"lat": 36.0, "lon": -109.0, "monthly": make_monthly(0.08, 0.15, 0)},
        {"lat": 37.0, "lon": -108.0, "monthly": make_monthly(0.08, 0.15, 1)},
        {"lat": 38.0, "lon": -107.0, "monthly": make_monthly(0.08, 0.15, 2)},
        {"lat": 39.0, "lon": -106.0, "monthly": make_monthly(0.08, 0.15, 3)},
        {"lat": 31.0, "lon": -99.0, "monthly": make_monthly(0.0, 1.5, 0)},
        {"lat": 32.0, "lon": -98.0, "monthly": make_monthly(0.0, 1.5, 1)},
        {"lat": 33.0, "lon": -97.0, "monthly": make_monthly(0.0, 1.5, 2)},
        {"lat": 34.0, "lon": -96.0, "monthly": make_monthly(0.0, 1.5, 3)},
        {"lat": 32.5, "lon": -97.5, "monthly": short_monthly},
    ]

    assigned, state_names = assign_cells_to_states(cells, geojson)
    coord_to_state = {(c["lat"], c["lon"]): st for c, st in zip(cells, assigned)}
    records, fdr_summary = compute_cell_trends({"T2M": {"cells": cells}}, coord_to_state)

    assert len(fdr_summary) == 3
    assert all("fallbacks" not in entry for entry in fdr_summary)
    assert len(records) == 3 * len(cells)

    aa_records = [r for r in records if r["state"] == "AA"]
    assert all(r["significant_fdr"] == 1 and r["slope_per_decade"] > 0.5 for r in aa_records)

    short_records = [r for r in records if r["lat"] == 32.5 and r["lon"] == -97.5]
    assert all(math.isnan(r["p"]) and r["significant_fdr"] == 0 for r in short_records)

    rows = aggregate_state_metrics(records, state_names, min_cells=4)
    ranked = rank_temperature_states(rows)
    assert [r["state"] for r in ranked] == ["AA", "BB"]
    assert ranked[0]["mean_clarity"] == pytest.approx(1.0)
    assert ranked[1]["mean_clarity"] == pytest.approx(0.0)
