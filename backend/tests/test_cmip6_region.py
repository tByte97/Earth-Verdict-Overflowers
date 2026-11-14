"""Offline unit and integration tests for tools/fetch_cmip6_region.py."""
from __future__ import annotations

import calendar
import datetime
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import netcdf_file

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import fetch_cmip6 as pt  # noqa: E402
import fetch_cmip6_region as reg  # noqa: E402


def _write_synthetic_nc3(
    path: Path,
    var: str,
    year: int,
    cal: str,
    lats: list[float],
    lons_360: list[float],
    monthly_vals: list[float] | np.ndarray,
    ref_date: str = "1950-01-01",
) -> None:
    """Create a synthetic daily NetCDF-3 file matching NCCS NCSS structure.

    `monthly_vals` can be length-12 scalar values (broadcast across cells) or shape (12, nlat, nlon).
    """
    ref_y, ref_m, ref_d = map(int, ref_date.split("-"))
    if cal in ("365_day", "noleap"):
        days_per_month = reg._DAYS_NOLEAP
        year_offset_days = (year - ref_y) * 365
        # Reference date assumed Jan 1 of ref_y for offset calculation
        assert ref_m == 1 and ref_d == 1
        start_day = year_offset_days
    elif cal in ("proleptic_gregorian", "standard", "gregorian"):
        days_per_month = tuple(calendar.monthrange(year, m)[1] for m in range(1, 13))
        start_day = (datetime.date(year, 1, 1) - datetime.date(ref_y, ref_m, ref_d)).days
    else:
        raise ValueError(f"Unexpected test calendar {cal}")

    n_days = sum(days_per_month)
    nlat, nlon = len(lats), len(lons_360)
    time_vals = np.arange(start_day, start_day + n_days, dtype=np.float64) + 0.5
    data = np.empty((n_days, nlat, nlon), dtype=np.float32)

    mv = np.asarray(monthly_vals, dtype=np.float32)
    pos = 0
    for m_idx, dim in enumerate(days_per_month):
        val = mv[m_idx]
        if np.ndim(val) == 0:
            data[pos : pos + dim, :, :] = float(val)
        else:
            data[pos : pos + dim, :, :] = val[None, :, :]
        pos += dim

    path.parent.mkdir(parents=True, exist_ok=True)
    with netcdf_file(str(path), "w") as nc:
        nc.createDimension("time", n_days)
        nc.createDimension("lat", nlat)
        nc.createDimension("lon", nlon)

        t_var = nc.createVariable("time", "d", ("time",))
        t_var.units = f"days since {ref_date} 00:00:00"
        t_var.calendar = cal
        t_var[:] = time_vals

        lat_var = nc.createVariable("lat", "f", ("lat",))
        lat_var[:] = np.asarray(lats, dtype=np.float32)

        lon_var = nc.createVariable("lon", "f", ("lon",))
        lon_var[:] = np.asarray(lons_360, dtype=np.float32)

        v_var = nc.createVariable(var, "f", ("time", "lat", "lon"))
        v_var[:] = data


def test_bbox_lon_conversion_and_validation():
    assert reg.to_lon360(-10.0) == pytest.approx(350.0)
    assert reg.to_lon360(22.0) == pytest.approx(22.0)
    assert reg.to_lon360(-180.0) == pytest.approx(180.0)

    assert reg.to_lon180(350.0) == pytest.approx(-10.0)
    assert reg.to_lon180(359.875) == pytest.approx(-0.125)
    assert reg.to_lon180(30.625) == pytest.approx(30.625)
    assert reg.to_lon180(180.0) == pytest.approx(180.0)

    assert reg.validate_bbox([44, -10, 53, 41]) == (44.0, -10.0, 53.0, 41.0)
    with pytest.raises(ValueError):
        reg.validate_bbox([53, 20, 44, 41])
    with pytest.raises(ValueError):
        reg.validate_bbox([44, 20, 53, 20])


def test_monthly_reduction_365_day_and_proleptic_leap(tmp_path: Path):
    lats = [50.125, 50.375]
    lons_360 = [350.125, 0.125]  # wraps across prime meridian: -9.875, 0.125

    # 365_day in leap year 2020 -> Feb has 28 days
    tas_k = [273.15 + m for m in range(1, 13)]
    nc_365_tas = tmp_path / "tas_365_2020.nc"
    _write_synthetic_nc3(nc_365_tas, "tas", 2020, "365_day", lats, lons_360, tas_k)
    m_tas, out_lat, out_lon = reg.reduce_nc_to_monthly(nc_365_tas, "tas", 2020)
    assert m_tas.dtype == np.float32
    assert m_tas.shape == (12, 2, 2)
    np.testing.assert_allclose(out_lat, lats, atol=1e-5)
    np.testing.assert_allclose(out_lon, [-9.875, 0.125], atol=1e-5)
    np.testing.assert_allclose(m_tas[:, 0, 0], np.arange(1, 13, dtype=np.float32), atol=1e-4)

    # pr in 365_day 2020: 1e-5 kg m-2 s-1 = 0.864 mm/day -> Feb = 0.864 * 28 = 24.192 mm
    pr_rate = [1e-5] * 12
    nc_365_pr = tmp_path / "pr_365_2020.nc"
    _write_synthetic_nc3(nc_365_pr, "pr", 2020, "365_day", lats, lons_360, pr_rate)
    m_pr_365, _, _ = reg.reduce_nc_to_monthly(nc_365_pr, "pr", 2020)
    assert m_pr_365[1, 0, 0] == pytest.approx(0.864 * 28, rel=1e-4)
    assert m_pr_365[0, 0, 0] == pytest.approx(0.864 * 31, rel=1e-4)

    # proleptic_gregorian in leap year 2020 -> Feb has 29 days
    nc_leap_pr = tmp_path / "pr_leap_2020.nc"
    _write_synthetic_nc3(nc_leap_pr, "pr", 2020, "proleptic_gregorian", lats, lons_360, pr_rate)
    m_pr_leap, _, _ = reg.reduce_nc_to_monthly(nc_leap_pr, "pr", 2020)
    assert m_pr_leap[1, 0, 0] == pytest.approx(0.864 * 29, rel=1e-4)

    # proleptic_gregorian in non-leap year 2021 -> Feb has 28 days
    nc_noleap_pr = tmp_path / "pr_2021.nc"
    _write_synthetic_nc3(nc_noleap_pr, "pr", 2021, "proleptic_gregorian", lats, lons_360, pr_rate)
    m_pr_2021, _, _ = reg.reduce_nc_to_monthly(nc_noleap_pr, "pr", 2021)
    assert m_pr_2021[1, 0, 0] == pytest.approx(0.864 * 28, rel=1e-4)

    # 360_day rejected clearly
    with pytest.raises(reg.IncompatibleModelError):
        reg.decode_time_axis(np.array([0.0]), "days since 1950-01-01", "360_day")


def test_seasonal_assembly_djf_across_year_boundary():
    # Shape (12, 1, 1)
    y1994 = np.zeros((12, 1, 1), dtype=np.float64)
    y1994[11] = 12.0  # Dec 1994
    y1995 = np.full((12, 1, 1), 10.0, dtype=np.float64)
    y1995[0] = 3.0   # Jan 1995
    y1995[1] = 6.0   # Feb 1995
    y1995[5] = 20.0  # Jun 1995
    y1995[6] = 22.0  # Jul 1995
    y1995[7] = 24.0  # Aug 1995

    tas_seas = reg._compute_seasonal({1994: y1994, 1995: y1995}, "tas", [1995])
    assert tas_seas["DJF"][1995][0, 0] == pytest.approx((12.0 + 3.0 + 6.0) / 3.0)
    assert tas_seas["JJA"][1995][0, 0] == pytest.approx((20.0 + 22.0 + 24.0) / 3.0)
    assert tas_seas["year"][1995][0, 0] == pytest.approx(np.mean(y1995))

    pr_seas = reg._compute_seasonal({1994: y1994, 1995: y1995}, "pr", [1995])
    assert pr_seas["DJF"][1995][0, 0] == pytest.approx(12.0 + 3.0 + 6.0)
    assert pr_seas["JJA"][1995][0, 0] == pytest.approx(20.0 + 22.0 + 24.0)
    assert pr_seas["year"][1995][0, 0] == pytest.approx(np.sum(y1995))


def test_grid_mismatch_rejected(tmp_path: Path):
    import threading

    lock = threading.Lock()
    reg.verify_and_store_grid(tmp_path, np.array([50.125, 50.375]), np.array([30.125]), lock, "M1")
    with pytest.raises(reg.IncompatibleModelError):
        reg.verify_and_store_grid(tmp_path, np.array([50.125, 50.625]), np.array([30.125]), lock, "M2")


def test_pipeline_resume_baseline_percentile_and_missing_model(tmp_path: Path, monkeypatch):
    models = ["M1", "M2", "M3", "M4_BROKEN"]
    lats = [50.125, 50.375]
    lons_360 = [30.125, 30.375]
    bbox = (50.0, 30.0, 51.0, 31.0)
    cache_dir = tmp_path / "cache" / "testreg"
    out_dir = tmp_path / "out"

    # Model-specific constant seasonal shifts so percentiles are analytical:
    # M1: hist tas = 10 C (283.15 K), ssp tas = 11 C (+1.0 C)
    # M2: hist tas = 12 C (285.15 K), ssp tas = 14 C (+2.0 C)
    # M3: hist tas = 14 C (287.15 K), ssp tas = 18 C (+4.0 C)
    # For pr:
    # M1: hist = 10 mm/mo, ssp = 12 mm/mo (+6 mm JJA/DJF, +24 mm year)
    # M2: hist = 20 mm/mo, ssp = 25 mm/mo (+15 mm JJA/DJF, +60 mm year)
    # M3: hist = 30 mm/mo, ssp = 40 mm/mo (+30 mm JJA/DJF, +120 mm year)
    model_tas = {"M1": (10.0, 11.0), "M2": (12.0, 14.0), "M3": (14.0, 18.0), "M4_BROKEN": (10.0, 11.0)}
    model_pr_mm = {"M1": (10.0, 12.0), "M2": (20.0, 25.0), "M3": (30.0, 40.0), "M4_BROKEN": (10.0, 12.0)}

    monkeypatch.setattr(pt, "pick_variant", lambda m, refresh=False: "r1i1p1f1")

    def fake_list_year_paths(model, scen, variant, var, refresh=False):
        y0, y1 = (reg.HIST_FETCH_START, reg.HIST_END) if scen == "historical" else (reg.SSP_START, reg.SSP_END)
        return {y: f"{model}/{scen}/{var}/{y}.nc" for y in range(y0, y1 + 1)}

    monkeypatch.setattr(pt, "list_year_paths", fake_list_year_paths)

    download_calls = []

    def fake_download(url_path, var, req_bbox, dest_nc, stop_event=None, retries=5, timeout=300):
        download_calls.append(url_path)
        model, scen, _, fname = url_path.split("/")
        year = int(fname.replace(".nc", ""))
        if model == "M4_BROKEN" and scen == "ssp585" and year == 2050:
            raise reg.MissingDataError("HTTP 404")

        is_hist = scen == "historical"
        if var == "tas":
            c_val = model_tas[model][0 if is_hist else 1]
            # Cell (0, 1) offset by +1.0 C to verify spatial indexing
            mvals = np.full((12, 2, 2), 273.15 + c_val, dtype=np.float32)
            mvals[:, 0, 1] += 1.0
        else:
            mm_val = model_pr_mm[model][0 if is_hist else 1]
            rates = [mm_val / (86400.0 * d) for d in reg._DAYS_NOLEAP]
            mvals = np.zeros((12, 2, 2), dtype=np.float32)
            for m_idx, r in enumerate(rates):
                mvals[m_idx, :, :] = r
        cal = "365_day" if model == "M2" else "proleptic_gregorian"
        if cal == "proleptic_gregorian" and var == "pr":
            mm_val = model_pr_mm[model][0 if is_hist else 1]
            days = [calendar.monthrange(year, m)[1] for m in range(1, 13)]
            for m_idx, d in enumerate(days):
                mvals[m_idx, :, :] = mm_val / (86400.0 * d)
        _write_synthetic_nc3(dest_nc, var, year, cal, lats, lons_360, mvals)

    monkeypatch.setattr(reg, "download_ncss_netcdf", fake_download)

    # First run: downloads all tasks, skips M4_BROKEN 2050 error without crashing
    finished, incomplete = reg.run_downloads(
        name="testreg",
        bbox=bbox,
        models=models,
        workers=2,
        cache_dir=cache_dir,
    )
    assert finished is True
    assert "M4_BROKEN" in incomplete
    first_call_count = len(download_calls)
    expected_total = len(models) * 2 * (21 + 3 * 86)
    assert first_call_count == expected_total

    # Second run (resume): M4_BROKEN still missing 1 file -> only retries that 1 missing file;
    # for the 3 complete models it performs ZERO requests.
    download_calls.clear()
    finished2, _ = reg.run_downloads(
        name="testreg",
        bbox=bbox,
        models=["M1", "M2", "M3"],
        workers=2,
        cache_dir=cache_dir,
    )
    assert finished2 is True
    assert len(download_calls) == 0

    # Finalize with all 4 models requested: M4_BROKEN excluded, succeeds with M1, M2, M3
    out, out_path = reg.finalize_region(
        name="testreg",
        bbox=bbox,
        models=models,
        cache_dir=cache_dir,
        out_dir=out_dir,
    )
    assert out_path.exists()
    raw_text = out_path.read_text(encoding="utf-8")
    assert "\n" not in raw_text and ": " not in raw_text
    loaded = json.loads(raw_text)

    assert loaded["models"] == ["M1", "M2", "M3"]
    assert loaded["grid"]["lat"] == pytest.approx(lats)
    assert loaded["grid"]["lon"] == pytest.approx([30.125, 30.375])

    # Baseline median across [10, 12, 14] is 12.0 (cell [0][1] is 13.0)
    assert loaded["baseline"]["tas"]["JJA"][0][0] == 12.0
    assert loaded["baseline"]["tas"]["JJA"][0][1] == 13.0
    assert loaded["baseline"]["tas"]["DJF"][0][0] == 12.0
    assert loaded["baseline"]["pr"]["JJA"][0][0] == 60.0  # 3 months * 20 mm
    assert loaded["baseline"]["pr"]["year"][0][0] == 240.0  # 12 months * 20 mm

    # Change percentiles across [1.0, 2.0, 4.0]:
    # p10 = 1.0 + 0.2*(2.0 - 1.0) = 1.2; p50 = 2.0; p90 = 2.0 + 0.8*(4.0 - 2.0) = 3.6
    jja_ssp585 = loaded["variables"]["tas"]["JJA"]["ssp585"]
    assert len(jja_ssp585["median"]) == 4
    for h_idx in range(4):
        assert jja_ssp585["low"][h_idx][0][0] == 1.2
        assert jja_ssp585["median"][h_idx][0][0] == 2.0
        assert jja_ssp585["high"][h_idx][0][0] == 3.6

    # pr JJA change across [6, 15, 30]: p10 = 6 + 0.2*9 = 7.8; p50 = 15.0; p90 = 15 + 0.8*15 = 27.0
    pr_jja = loaded["variables"]["pr"]["JJA"]["ssp126"]
    assert pr_jja["low"][1][0][0] == 7.8
    assert pr_jja["median"][1][0][0] == 15.0
    assert pr_jja["high"][1][0][0] == 27.0

    # Requiring >= 3 complete models: requesting only 2 complete models must fail
    with pytest.raises(RuntimeError, match="Need at least 3"):
        reg.finalize_region(
            name="too_few",
            bbox=bbox,
            models=["M1", "M2", "M4_BROKEN"],
            cache_dir=cache_dir,
            out_dir=out_dir,
        )
