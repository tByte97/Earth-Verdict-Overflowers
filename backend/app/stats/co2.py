"""Pure CO2 radiative forcing and transient warming physics (no network calls).

Physical constants and citations:
- Mass-to-mixing-ratio conversion: 1 ppm atmospheric CO2 ≈ 2.13 GtC ≈ 7.82 Gt CO2
  (Global Carbon Budget, Friedlingstein et al., Earth Syst. Sci. Data, 2023).
- Airborne fraction: ~0.44 (range 0.40–0.48) of emitted CO2 remains in the atmosphere
  over multi-decadal timescales (Global Carbon Budget, Friedlingstein et al., 2023).
- Radiative forcing formula: ΔF = 5.35 · ln(C / C0) W/m²
  (Myhre et al., Geophys. Res. Lett. 25(14), 2715–2718, 1998).
- Effective radiative forcing for doubled CO2: F2x = 3.93 W/m²
  (IPCC AR6 WGI, Chapter 7, Forster et al., 2021).
- Transient Climate Response (TCR): best estimate 1.8 °C, likely range 1.4–2.2 °C
  (IPCC AR6 WGI, Chapter 7, Forster et al., 2021), giving ΔT ≈ TCR · ΔF / F2x.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Optional

from .trend import analyze_trend

GT_CO2_PER_PPM = 7.82
AIRBORNE_FRACTION_CENTRAL = 0.44
AIRBORNE_FRACTION_LOW = 0.40
AIRBORNE_FRACTION_HIGH = 0.48

RF_COEFF_MYHRE = 5.35
F2X_CO2_AR6 = 3.93
TCR_CENTRAL = 1.8
TCR_LOW = 1.4
TCR_HIGH = 2.2


@dataclass(frozen=True)
class RangeEstimate:
    central: float
    low: float
    high: float


@dataclass(frozen=True)
class PlantContribution:
    total_emitted_gt: float
    added_ppm: RangeEstimate
    added_forcing_w_m2: RangeEstimate
    transient_warming_c: RangeEstimate


@dataclass(frozen=True)
class ConcentrationImpact:
    c_ppm: float
    c0_ppm: float
    forcing_w_m2: float
    transient_warming_c: RangeEstimate


@dataclass(frozen=True)
class GlobalCo2Summary:
    latest_month: str
    latest_ppm: float
    yoy_growth_ppm: Optional[float]
    sen_slope_ppm_per_year: float
    sen_ci_low: float
    sen_ci_high: float
    mk_p: float


def plant_contribution(
    mt_co2_per_year: float,
    years: float,
    c_now_ppm: float,
) -> PlantContribution:
    """Compute cumulative CO2 emissions, added ppm, forcing, and transient warming for a source.

    Uses Global Carbon Budget airborne fraction (0.44, range 0.40–0.48), 7.82 Gt CO2/ppm,
    Myhre et al. (1998) ΔF = 5.35·ln((C + ΔC)/C), and IPCC AR6 F2x = 3.93 W/m²,
    TCR = 1.8 °C (range 1.4–2.2 °C).
    """
    if mt_co2_per_year <= 0.0:
        raise ValueError("mt_co2_per_year must be positive")
    if years <= 0.0:
        raise ValueError("years must be positive")
    if c_now_ppm <= 0.0:
        raise ValueError("c_now_ppm must be positive")

    total_gt = (mt_co2_per_year * years) / 1000.0
    dppm_c = total_gt * AIRBORNE_FRACTION_CENTRAL / GT_CO2_PER_PPM
    dppm_l = total_gt * AIRBORNE_FRACTION_LOW / GT_CO2_PER_PPM
    dppm_h = total_gt * AIRBORNE_FRACTION_HIGH / GT_CO2_PER_PPM

    df_c = RF_COEFF_MYHRE * math.log((c_now_ppm + dppm_c) / c_now_ppm)
    df_l = RF_COEFF_MYHRE * math.log((c_now_ppm + dppm_l) / c_now_ppm)
    df_h = RF_COEFF_MYHRE * math.log((c_now_ppm + dppm_h) / c_now_ppm)

    dt_c = TCR_CENTRAL * df_c / F2X_CO2_AR6
    dt_l = TCR_LOW * df_l / F2X_CO2_AR6
    dt_h = TCR_HIGH * df_h / F2X_CO2_AR6

    return PlantContribution(
        total_emitted_gt=total_gt,
        added_ppm=RangeEstimate(central=dppm_c, low=dppm_l, high=dppm_h),
        added_forcing_w_m2=RangeEstimate(central=df_c, low=df_l, high=df_h),
        transient_warming_c=RangeEstimate(central=dt_c, low=dt_l, high=dt_h),
    )


def what_if_concentration(
    c_ppm: float,
    c0_ppm: float = 280.0,
) -> ConcentrationImpact:
    """Compute radiative forcing ΔF = 5.35·ln(C/C0) and IPCC AR6 transient warming range."""
    if c_ppm <= 0.0 or c0_ppm <= 0.0:
        raise ValueError("CO2 concentrations must be positive")

    df = RF_COEFF_MYHRE * math.log(c_ppm / c0_ppm)
    return ConcentrationImpact(
        c_ppm=c_ppm,
        c0_ppm=c0_ppm,
        forcing_w_m2=df,
        transient_warming_c=RangeEstimate(
            central=TCR_CENTRAL * df / F2X_CO2_AR6,
            low=TCR_LOW * df / F2X_CO2_AR6,
            high=TCR_HIGH * df / F2X_CO2_AR6,
        ),
    )


def summarize_global_co2(
    months: Sequence[str],
    values: Sequence[Optional[float]],
    *,
    since_year: int = 1980,
) -> GlobalCo2Summary:
    """Summarize NOAA GML global monthly CO2: latest level, YoY growth, and annual Sen slope."""
    if len(months) != len(values) or not months:
        raise ValueError("months and values must be non-empty and have the same length")

    by_ym: dict[str, float] = {}
    by_year: dict[int, list[float]] = defaultdict(list)
    latest_month: Optional[str] = None
    latest_ppm: Optional[float] = None

    for ym, val in zip(months, values):
        if val is None or not math.isfinite(float(val)):
            continue
        fval = float(val)
        by_ym[ym] = fval
        yr = int(ym.split("-")[0])
        if yr >= since_year:
            by_year[yr].append(fval)
        if latest_month is None or ym > latest_month:
            latest_month = ym
            latest_ppm = fval

    if latest_month is None or latest_ppm is None:
        raise ValueError("No valid CO2 observations found")

    ly, lm = latest_month.split("-")
    prev_ym = f"{int(ly) - 1:04d}-{lm}"
    yoy = (latest_ppm - by_ym[prev_ym]) if prev_ym in by_ym else None

    full_years = sorted(yr for yr, vals in by_year.items() if len(vals) >= 10)
    if len(full_years) < 3:
        raise ValueError(f"Need at least 3 complete years since {since_year} for trend analysis")
    annual_means = [sum(by_year[yr]) / len(by_year[yr]) for yr in full_years]
    trend = analyze_trend(full_years, annual_means, start_year=full_years[0])
    assert trend is not None

    return GlobalCo2Summary(
        latest_month=latest_month,
        latest_ppm=latest_ppm,
        yoy_growth_ppm=yoy,
        sen_slope_ppm_per_year=trend.sen.slope_per_year,
        sen_ci_low=trend.sen.ci_low_per_year,
        sen_ci_high=trend.sen.ci_high_per_year,
        mk_p=trend.mk.p,
    )
