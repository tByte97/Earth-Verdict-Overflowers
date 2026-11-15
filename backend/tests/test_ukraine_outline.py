"""Tests for tools/ukraine_outline.py and per-cell fade weights in built layers."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ukraine_outline as uo  # noqa: E402


@pytest.mark.parametrize("name,lat,lon", [
    ("Simferopol", 44.95, 34.10),
    ("Sevastopol", 44.60, 33.50),
    ("Donetsk", 48.00, 37.80),
    ("Luhansk", 48.57, 39.30),
    ("Kyiv", 50.45, 30.52),
])
def test_ukraine_outline_includes_crimea_donetsk_luhansk(name, lat, lon):
    assert uo.in_ukraine(lat, lon), f"{name} ({lat}, {lon}) should be inside Ukraine"
    assert uo.distance_to_ukraine_km(lat, lon) == 0.0
    assert uo.cell_fade(lat, lon) == 1.0


@pytest.mark.parametrize("name,lat,lon", [
    ("Rostov-on-Don", 47.23, 39.70),
    ("Minsk", 53.90, 27.56),
    ("Warsaw", 52.23, 21.00),
])
def test_ukraine_outline_excludes_neighbouring_cities(name, lat, lon):
    assert not uo.in_ukraine(lat, lon), f"{name} ({lat}, {lon}) should be outside Ukraine"
    assert uo.distance_to_ukraine_km(lat, lon) > 0.0
    assert 0.0 < uo.cell_fade(lat, lon) < 1.0


def test_smoothstep_fade_bounds_and_monotonicity():
    assert uo.smoothstep_fade(0.0) == 1.0
    assert uo.smoothstep_fade(uo.FADE_KM) == 0.0
    assert uo.smoothstep_fade(uo.FADE_KM + 50.0) == 0.0
    prev = 1.0
    for d in range(25, int(uo.FADE_KM), 25):
        val = uo.smoothstep_fade(float(d))
        assert 0.0 <= val <= prev
        prev = val


def test_built_layers_store_irregular_fade_set_with_no_zeros():
    layers_dir = ROOT / "data" / "layers"
    for path in sorted(layers_dir.glob("trends_*.geojson")):
        gj = json.loads(path.read_text(encoding="utf-8"))
        coords = [(f["properties"]["lat"], f["properties"]["lon"]) for f in gj["features"]]
        fades = [f["properties"]["fade"] for f in gj["features"]]
        assert all(0.0 < f <= 1.0 for f in fades)
        # Stored grid is irregular (not a full lat x lon rectangle).
        n_lats = len({lat for lat, _ in coords})
        n_lons = len({lon for _, lon in coords})
        assert len(coords) < n_lats * n_lons

    for path in sorted(layers_dir.glob("years_*.json")):
        ym = json.loads(path.read_text(encoding="utf-8"))
        assert len(ym["fade"]) == len(ym["lat"]) == len(ym["lon"])
        assert all(0.0 < f <= 1.0 for f in ym["fade"])
        n_lats = len(set(ym["lat"]))
        n_lons = len(set(ym["lon"]))
        assert len(ym["lat"]) < n_lats * n_lons
