# Показові справи (заглушка для фронтенду)

Ряди в цих файлах **справжні** (NASA POWER, NOAA). Статистика поки тимчасова (`meta.stub: true`):
числа можуть трохи змінитися, коли буде готовий власний модуль статистики (#12). Структура
полів зафіксована в `backend/app/models.py` і змінюється лише через PR.

| Файл | Твердження | Вердикт | Що на ньому перевіряти |
|---|---|---|---|
| `mock.json` = `kyiv-summer-heat.json` | Summers in Kyiv are getting hotter | `confirmed` | Повна картка, станція з пропусками (4 роки `null`), сценарії |
| `lviv-drier.json` | Lviv is getting drier | `refuted` | Тренд у протилежний бік, станції немає (`witness: null`) |
| `kyiv-winter-snow.json` | Kyiv winters have more snow now | `not_proven` | «Скільки ще чекати» (`years_to_wait: 27`), сезон через межу року (DJF) |

## Що де лежить

- `series` — одне значення на рік. `value: null` означає «немає даних», рік з масиву не викидається.
- `sen` — нахил тренду й 95% інтервал (`ci_low`, `ci_high` — на 10 років). Лінія тренду:
  `intercept + slope_per_year × (рік − case.start_year)`.
- `mk`, `ols`, `robustness` — технічні числа для розгортки (#3).
- `witness` — станція: ряд, `coverage` (частка років із даними), `agreement`; `null` = станції немає.
- `steps` — 8 кроків для блоку «Як ми це порахували» (#5): `title`, `value`, `detail`.
- `detection` — **A. «Скільки ще чекати»** (#6): для швидкостей зміни `multipliers` (×0.5…×2) —
  `years_needed`, скільки всього років спостережень треба, щоб тренд став помітним. Є вже `n_years`.
  Формула в `backend/app/models.py`, можна рахувати і на фронтенді для плавного повзунка.
- `extrapolation` — **B. Продовження тренду** (#7): лінії до 2050 для «зупиниться / удвічі повільніше /
  як зараз / в 1.5 раза швидше» з віялом із 95% інтервалу нахилу. Обов'язковий підпис `note`: це не прогноз.
- `scenarios` — **C. Сценарії NASA** (#7, дані #14). Зараз `synthetic: true`: криві стилізовані, не CMIP6. `median/low/high` —
  зміна відносно `baseline_value` за `baseline_period`. **На вердикт не впливають.**
- `provenance` — джерело кожного числа з посиланням.

Перегенерувати: `backend/.venv/bin/python tools/build_cases.py` (потрібні дані з `tools/fetch_data.py`).
