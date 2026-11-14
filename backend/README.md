# Earth Verdict backend

FastAPI service that turns a claim (`CaseSpec`) into a verdict (`CheckResult`) using NASA POWER,
NASA Giovanni and NOAA station data. Contracts live in `app/models.py`; the showcase cases in
`data/cases/` are produced by the same code (`app/check.py`).

## Run locally

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn app.main:app --app-dir backend --reload   # http://127.0.0.1:8000
```

The frontend dev server (`frontend/`, Vite) proxies `/api` to `http://127.0.0.1:8000`.

| Env var | Meaning |
|---|---|
| `OFFLINE=1` | Never call external APIs; serve only what is in `data/cache/` (demo mode) |
| `EV_DATA_DIR` | Data folder (default `data/`) with `cache/`, `cases/`, `layers/` |
| `EARTHDATA_TOKEN` | Needed only for Giovanni variables (`precip_gpm`, `evapotranspiration`); or put it in `~/.config/earthdata/token` |
| `EV_CORS_ORIGINS` | Comma-separated origins allowed to call the API (default: Vite dev server) |

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/api/variables` | Whitelist of variables (`Variable[]`) |
| GET | `/api/places?q=Kyiv` | Geocoder candidates (`Place[]`), capitals and big cities first |
| POST | `/api/check` | Body `CaseSpec` → `CheckResult` (takes a few seconds on first call, then cached) |
| GET | `/api/cases` | Showcase cases: id, claim, place, verdict |
| GET | `/api/cases/{id}` | One showcase `CheckResult` (works offline) |
| GET | `/api/compounds` | Whitelist of atmospheric compounds (`Compound[]`) |
| POST | `/api/event` | Body `EventSpec` → BACI pollutant impact `EventResult` |
| GET | `/api/events` | Showcase pollutant events: id, label, month, place, compound, verdict |
| GET | `/api/events/{id}` | One showcase `EventResult` (works offline) |
| POST | `/api/co2-impact` | Body `Co2ImpactSpec` → cumulative CO₂ forcing & warming `Co2ImpactResult` |
| GET | `/api/co2/global` | Latest NOAA GML global monthly CO₂, YoY growth, and 1980+ Sen slope |
| POST | `/api/chat` | `{kind: check\|event\|co2, result, question?, lang?}` → plain-language explanation from Gemini (`GEMINI_API_KEY` or `~/.config/gemini/api_key`, model `EV_LLM_MODEL`); numbers are checked against the result |
| GET | `/api/grid?variable_id=air_temp&season=JJA` | GeoJSON trend layer for the globe (FDR-corrected); top level has `variable_id`, `start_year`, `end_year` and `pair` (nearest cells with opposite significant trends, or null) |

Each `steps[]` item has `fields` (dot paths into the result that the step summarises) and step-specific fields: `raw` → `n_months`, `monthly`; `season` → `months`, `aggregation`, `years_dropped`; `random_check` → `alpha`, `methods_agree`, `methods_reason`. They are `null` on the other steps.

Errors always look like `{"error": {"code": "...", "message": "..."}}` with codes
`unknown_variable`, `short_series`, `bad_request` (400), `place_not_found` (404),
`source_unavailable` (503).

```bash
curl -s localhost:8000/api/check -H 'Content-Type: application/json' -d '{
  "claim_text": "Summers in Kyiv are getting hotter", "variable_id": "air_temp",
  "place": {"place_id": "om:703448", "name": "Kyiv, Ukraine", "lat": 50.45, "lon": 30.52},
  "season": "JJA", "start_year": 1981, "end_year": 2025, "claim_direction": "increase"}' | jq .verdict
```

## Tests

```bash
backend/.venv/bin/python -m pytest -q backend/tests     # offline, no network needed
```
