"""Ukraine border outline, point-in-polygon and smooth fade weights.

Outline source: Natural Earth 10m Admin 0 Countries (Ukraine point of view,
`ne_10m_admin_0_countries_ukr`, public domain), simplified with RDP (0.01 deg)
into tools/ukraine_outline.json. Includes Crimea, Donetsk and Luhansk.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

EARTH_RADIUS_KM = 6371.0
FADE_KM = 460.0
OUTLINE_PATH = Path(__file__).resolve().parent / "ukraine_outline.json"


@lru_cache(maxsize=1)
def _outline():
    data = json.loads(OUTLINE_PATH.read_text(encoding="utf-8"))
    geom = data["geometry"]
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]

    # Precompute unit-sphere segment vectors for fast vectorized border distance.
    a_pts, b_pts = [], []
    for poly in polys:
        for ring in poly:
            for i in range(len(ring) - 1):
                a_pts.append(ring[i])
                b_pts.append(ring[i + 1])
    a_arr = np.asarray(a_pts, dtype=float)
    b_arr = np.asarray(b_pts, dtype=float)
    va = _to_unit_vec(a_arr[:, 1], a_arr[:, 0])
    vb = _to_unit_vec(b_arr[:, 1], b_arr[:, 0])
    n_vec = np.cross(va, vb)
    n_norm = np.linalg.norm(n_vec, axis=-1, keepdims=True)
    valid = n_norm[:, 0] > 1e-12
    n_hat = np.divide(n_vec, np.where(valid[:, None], n_norm, 1.0))
    # u = n_hat x va, v = vb x n_hat lie in the great-circle plane orthogonal to n_hat.
    u_vec = np.cross(n_hat, va)
    v_vec = np.cross(vb, n_hat)
    return polys, va, vb, n_hat, u_vec, v_vec, valid


def _to_unit_vec(lat_deg, lon_deg) -> np.ndarray:
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    clat = np.cos(lat)
    return np.stack([clat * np.cos(lon), clat * np.sin(lon), np.sin(lat)], axis=-1)


def _point_in_ring(lat: float, lon: float, ring: list[list[float]]) -> bool:
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def in_ukraine(lat: float, lon: float) -> bool:
    """True when (lat, lon) lies inside Ukraine's outline (including Crimea, Donetsk, Luhansk)."""
    polys, *_ = _outline()
    for poly in polys:
        if _point_in_ring(lat, lon, poly[0]) and not any(_point_in_ring(lat, lon, hole) for hole in poly[1:]):
            return True
    return False


def distances_to_ukraine_km(coords: list[tuple[float, float]]) -> np.ndarray:
    """Great-circle distance in km from each (lat, lon) to Ukraine's border (0 inside)."""
    if not coords:
        return np.zeros(0, dtype=float)
    _, va, vb, n_hat, u_vec, v_vec, valid = _outline()
    arr = np.asarray(coords, dtype=float)
    inside = np.array([in_ukraine(float(lat), float(lon)) for lat, lon in arr], dtype=bool)
    out = np.zeros(len(arr), dtype=float)
    if inside.all():
        return out

    pts = arr[~inside]
    p = _to_unit_vec(pts[:, 0], pts[:, 1])  # (K, 3)
    pn = p @ n_hat.T
    on_arc = valid[None, :] & ((p @ u_vec.T) >= 0.0) & ((p @ v_vec.T) >= 0.0)
    dot_q = np.sqrt(np.clip(1.0 - pn * pn, 0.0, 1.0))
    dot_end = np.maximum(p @ va.T, p @ vb.T)
    best_dot = np.where(on_arc, dot_q, dot_end).max(axis=1)
    angles = 2.0 * np.arcsin(np.sqrt(np.clip((1.0 - best_dot) * 0.5, 0.0, 1.0)))
    out[~inside] = EARTH_RADIUS_KM * angles
    return out


def distance_to_ukraine_km(lat: float, lon: float) -> float:
    return float(distances_to_ukraine_km([(lat, lon)])[0])


def smoothstep_fade(dist_km: float, fade_km: float = FADE_KM) -> float:
    if dist_km <= 0.0:
        return 1.0
    if dist_km >= fade_km:
        return 0.0
    t = 1.0 - dist_km / fade_km
    return round(t * t * (3.0 - 2.0 * t), 2)


def cells_fade(coords: list[tuple[float, float]], fade_km: float = FADE_KM) -> list[float]:
    """Per-cell fade weight in [0, 1] rounded to 2 decimals: 1 inside, smoothstep to 0 at fade_km."""
    dists = distances_to_ukraine_km(coords)
    t = np.clip(1.0 - dists / fade_km, 0.0, 1.0)
    vals = np.where(dists <= 0.0, 1.0, t * t * (3.0 - 2.0 * t))
    return [round(float(v), 2) for v in vals]


def cell_fade(lat: float, lon: float, fade_km: float = FADE_KM) -> float:
    return smoothstep_fade(distance_to_ukraine_km(lat, lon), fade_km)
