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

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class BandPoint(Strict):
    year: int
    low: float              # нижня межа 95% смуги нахилу, у одиницях змінної
    mid: float              # сама лінія Сена в цей рік
    high: float


class Baseline(Strict):
    """Центр для кольорів смужок років: value − mean. Лише для основного ряду."""
    kind: Literal["normal_1991_2020", "series_mean"]   # series_mean: ряд покриває 1991–2020 гірше ніж на 24 роки з 30
    period: str             # "1991-2020" або діапазон років ряду
    mean: float
    n_years: int


class Sen(Strict):
    slope_per_year: float
    slope_per_decade: float
    ci_low: float           # 95% інтервал, на 10 років
    ci_high: float
    intercept: float        # значення лінії тренду в start_year
    pivot_year: float       # медіана років із даними; лінія Сена проходить через (pivot_year, pivot_value)
    pivot_value: float
    band: list[BandPoint]   # по запису на кожен рік start_year…end_year; віяло прямих крізь опору з нахилами ci_low/ci_high (невизначеність нахилу, не окремих років)


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


class DetectionHistoryPoint(Strict):
    end_year: int
    n_observations: int = Field(ge=0)
    p: Optional[float] = Field(ge=0, le=1)
    correction: Optional[Literal["hamed_rao", "none"]]
    status: Literal["ok", "short_series"]


class DetectionHistory(Strict):
    """Observed prefix checks; independent of the AR(1) detection power simulation."""
    alpha: float = Field(gt=0, lt=1)
    min_observations: int = Field(ge=3)
    method: Literal["sen_mann_kendall"]
    start_year: int
    points: list[DetectionHistoryPoint] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_points(self):
        previous_count = 0
        for index, point in enumerate(self.points):
            if point.end_year != self.start_year + index:
                raise ValueError("History must retain every calendar year in order")
            if point.n_observations - previous_count not in (0, 1):
                raise ValueError("Invalid history observation counts")
            previous_count = point.n_observations
            enough = point.n_observations >= self.min_observations
            if enough != (point.status == "ok") or enough != (point.p is not None):
                raise ValueError("History status/p must match the observation threshold")
            if enough != (point.correction is not None):
                raise ValueError("History correction must identify each performed test")
        return self


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
    baseline: Baseline
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
    detection_history: Optional[DetectionHistory] = None  # #6: additive, old responses remain valid
    extrapolation: Extrapolation        # B: продовження тренду, підпис «сценарій, не прогноз»
    scenarios: Optional[Scenarios]      # C: сценарії CMIP6; жоден із трьох не впливає на verdict
    provenance: list[Provenance]
    meta: Meta

    @model_validator(mode="after")
    def history_matches_case(self):
        history = self.detection_history
        if history is not None:
            if history.start_year != self.case.start_year or history.points[-1].end_year != self.case.end_year:
                raise ValueError("History period must match the observed case")
            observations = {point.year: point.value for point in self.series}
            count = 0
            for point in history.points:
                count += observations.get(point.end_year) is not None
                if point.n_observations != count:
                    raise ValueError("History counts must match non-missing case observations")
        return self


class ErrorBody(Strict):
    code: Literal["unknown_variable", "place_not_found", "short_series", "source_unavailable",
                  "llm_unavailable", "bad_request"]
    message: str


class ErrorResponse(Strict):
    error: ErrorBody
