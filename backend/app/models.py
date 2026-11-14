"""Спільні контракти Earth Verdict: CaseSpec (що перевіряємо) і CheckResult (що отримали).

Базова версія — розділ 3 у docs/08-tz.md. Розширення під задачі візуалізації (#9):
- `value: null` у рядах означає «немає даних за цей рік» (рік не викидається з масиву);
- `steps` — кроки обробки для блоку «Як ми це порахували» (#5);
- `scenarios` — сценарії майбутнього (#7), окремо від вердикту про минуле;
- `meta` — службова інформація (чи це заглушка, яка версія розрахунку).
Змінювати контракт лише через PR із попередженням команди.
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

Season = Union[Literal["year", "DJF", "MAM", "JJA", "SON"], int]  # int: місяць 1–12


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- CaseSpec ----------

class Place(Strict):
    place_id: str
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class CaseSpec(Strict):
    claim_text: str
    variable_id: str
    place: Place
    season: Season
    start_year: int
    end_year: int
    claim_direction: Literal["increase", "decrease", "change"]


# ---------- CheckResult ----------

class Variable(Strict):
    id: str
    label: str
    units: str
    definition: str
    caveat: Optional[str] = None


class YearValue(Strict):
    year: int
    value: Optional[float]  # None = за цей рік даних немає (пропуск показуємо чесно)


class Sen(Strict):
    slope_per_year: float
    slope_per_decade: float
    ci_low: float           # 95% інтервал, на 10 років
    ci_high: float
    intercept: float        # значення лінії тренду в start_year


class MannKendall(Strict):
    p: float
    tau: float
    z: float
    correction: Literal["hamed_rao", "none"]


class OLS(Strict):
    slope_per_year: float
    p: float
    r2: float
    n_eff: float            # ефективний обсяг вибірки з поправкою на автокореляцію


class RobustnessWindow(Strict):
    start_year: int
    end_year: int
    p: float
    slope_per_decade: float
    significant: bool


class RobustnessSummary(Strict):
    significant: int        # скільки вікон значущі в тому ж напрямку, що й основне
    total: int


class Station(Strict):
    id: str
    name: str
    lat: float
    lon: float
    distance_km: float


class WitnessSen(Strict):
    slope_per_decade: float
    ci_low: float
    ci_high: float


class WitnessMK(Strict):
    p: float


class WitnessRates(Strict):
    """Чи однаково швидко змінюються реаналіз і станція (тренд ряду «станція − реаналіз»
    на спільних роках). На вердикт не впливає: вердикт дивиться лише на напрямок."""
    common_years: int
    main_slope_per_decade: float      # реаналіз на тих самих роках, що й станція
    witness_slope_per_decade: float
    difference_per_decade: float      # > 0: станція змінюється швидше
    ci_low: float                     # 95% інтервал різниці, на 10 років
    ci_high: float
    p: float
    consistent: bool                  # True = значущої різниці швидкостей немає


class Witness(Strict):
    station: Station
    series: list[YearValue]
    coverage: float         # частка років із даними, 0–1
    method_note: Optional[str] = None
    sen: WitnessSen
    mk: WitnessMK
    agreement: Literal["agree", "one_source", "disagree"]
    rates: Optional[WitnessRates] = None   # None = замало спільних років (< 15)


class Step(Strict):
    """Один крок обробки для блоку «Як ми це порахували»."""
    id: Literal["raw", "season", "yearly", "trend", "random_check", "robustness", "witness", "verdict"]
    title: str              # коротко, простою мовою
    value: str              # головна цифра кроку з одиницями
    detail: str             # одне речення пояснення


class ScenarioPath(Strict):
    id: Literal["ssp126", "ssp245", "ssp585"]
    label: str              # людською мовою: «Світ різко скорочує викиди»
    years: list[int]
    median: list[float]     # зміна відносно бази, у одиницях змінної
    low: list[float]        # розкид моделей (10-й перцентиль)
    high: list[float]       # 90-й перцентиль


class Scenarios(Strict):
    synthetic: bool         # True = стилізовані криві, ще не CMIP6
    source: str
    baseline_period: str    # напр. "1995-2014"
    baseline_value: float   # значення змінної в базовому періоді (за спостереженнями)
    note: str               # «Це сценарії моделей, а не прогноз»
    paths: list[ScenarioPath]


class Detection(Strict):
    """A. «Скільки ще чекати»: статистика виявлення, не прогноз.
    years_needed[i] = скільки всього років спостережень треба, щоб наш тест (той самий, що дає
    вердикт) у ≥80% випадків помітив тренд зі швидкістю slope_per_year × multipliers[i] на тлі
    шуму цього ряду (симуляція AR(1) з residual_sd і phi). None = понад 250 років або нахил 0.
    Узгоджено з вердиктом: years_to_wait = years_needed[×1] − n_years (коли це > 0).
    Для плавного повзунка між точками інтерполювати лінійно в координатах log(k) — log(years)."""
    residual_sd: float
    phi: float              # автокореляція залишків (lag-1), обмежена 0…0.9
    slope_per_year: float
    n_years: int            # скільки років уже є
    multipliers: list[float]
    years_needed: list[Optional[float]]  # None = нахил нульовий, виявити неможливо


class ExtrapolationPath(Strict):
    id: Literal["stop", "slower", "same", "faster"]
    label: str
    multiplier: float
    central: list[float]
    low: list[float]        # з 95% інтервалу нахилу Сена
    high: list[float]


class Extrapolation(Strict):
    """B. Продовження тренду: «що буде, якщо швидкість зміни стане такою». Не прогноз."""
    note: str
    from_year: int
    from_value: float       # значення лінії тренду в from_year
    years: list[int]
    paths: list[ExtrapolationPath]


class Provenance(Strict):
    what: str
    source: str
    product: str
    url: str                # без токенів
    retrieved_at: str
    license: str


class Meta(Strict):
    stub: bool              # True = файл для верстки, числа можуть змінитися
    stats_engine: str
    generated_at: str


class CheckResult(Strict):
    case: CaseSpec
    variable: Variable
    series: list[YearValue]
    sen: Sen
    mk: MannKendall
    ols: OLS
    robustness: list[RobustnessWindow]
    robustness_summary: RobustnessSummary
    witness: Optional[Witness]          # None = станції-свідка немає (no_station)
    verdict: Literal["confirmed", "refuted", "not_proven"]
    reason: Literal["significant_trend", "opposite_trend", "not_significant", "short_series",
                    "sources_disagree", "not_robust"]
    years_to_wait: Optional[int]        # лише для not_proven
    steps: list[Step]
    detection: Detection                # A: повзунок «швидкість ×0.5…×2 → скільки років треба»
    extrapolation: Extrapolation        # B: продовження тренду, підпис «сценарій, не прогноз»
    scenarios: Optional[Scenarios]      # C: сценарії CMIP6; жоден із трьох не впливає на verdict
    provenance: list[Provenance]
    meta: Meta


class ErrorBody(Strict):
    code: Literal["unknown_variable", "place_not_found", "short_series", "source_unavailable",
                  "llm_unavailable", "bad_request"]
    message: str


class ErrorResponse(Strict):
    error: ErrorBody


# ---------- Pollutant Event Impact & CO2 Physics ----------

class Compound(Strict):
    id: str
    label: str
    units: str
    definition: str
    caveat: Optional[str] = None
    product: str
    first_year: int
    last_year: int
    local_signal: bool
    kind: Literal["satellite", "reanalysis"]


class MonthValue(Strict):
    month: str
    value: Optional[float]


class EventSpec(Strict):
    compound_id: str
    place: Place
    event_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    event_label: str
    window_years: int = Field(default=3, ge=1, le=5)
    use_control: bool = True


class WindowSummary(Strict):
    start: str
    end: str
    mean: Optional[float]
    n: int


class PlaceboCheck(Strict):
    event_month: str
    effect: float
    p: float


class EventSen(Strict):
    slope_per_year: float
    ci_low: float
    ci_high: float


class EventStep(Strict):
    id: Literal["data", "seasons", "control", "before_after", "chance", "placebo", "verdict"]
    title: str
    value: str
    detail: str


class EventResult(Strict):
    spec: EventSpec
    compound: Compound
    site: list[MonthValue]
    control: Optional[list[MonthValue]]
    before: WindowSummary
    after: WindowSummary
    effect: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    bootstrap_ci_low: Optional[float]
    bootstrap_ci_high: Optional[float]
    p: Optional[float]
    relative_change: Optional[float]
    placebo: list[PlaceboCheck]
    placebo_larger: int
    verdict: Literal["clear_change", "not_proven"]
    direction: Literal["increase", "decrease", "none"]
    reason: Literal["clear_change", "not_significant", "placebo_also_changes", "too_short", "no_placebo"]
    sen_before: Optional[EventSen]
    sen_after: Optional[EventSen]
    steps: list[EventStep]
    provenance: list[Provenance]
    meta: Meta


class Co2ImpactSpec(Strict):
    mt_co2_per_year: float = Field(gt=0, le=50_000)   # world fossil CO2 is ~37,000 Mt/yr
    years: float = Field(gt=0, le=200)
    what_if_ppm: Optional[float] = Field(default=None, ge=150, le=2_000)
    c0_ppm: float = Field(default=280.0, ge=150, le=2_000)
    label: Optional[str] = Field(default=None, max_length=120)


class Co2Range(Strict):
    central: float
    low: float
    high: float


class Co2GlobalSummary(Strict):
    latest_month: str
    latest_ppm: float
    yoy_growth_ppm: Optional[float]
    sen_slope_ppm_per_year: float
    sen_ci_low: float
    sen_ci_high: float
    series: list[MonthValue]


class Co2ImpactResult(Strict):
    spec: Co2ImpactSpec
    total_emitted_gt: float
    added_ppm: Co2Range
    added_forcing_w_m2: Co2Range
    transient_warming_c: Co2Range
    what_if_forcing_w_m2: Optional[float] = None
    what_if_warming_c: Optional[Co2Range] = None
    global_co2: Co2GlobalSummary
    explanation: str
    provenance: list[Provenance]


# ---------- Explanations (Gemini) ----------

class ChatRequest(Strict):
    kind: Literal["check", "event", "co2"]
    result: dict
    question: Optional[str] = Field(default=None, max_length=300)
    lang: Literal["en", "uk"] = "en"


class ChatResponse(Strict):
    text: str
    model: str
    grounded: bool      # False: the model's answer used a number not in the result; text is the built-in summary
