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
| `EV_RATE_LIMIT_EXEMPT_LOCAL` | Set to `1` to exempt unproxied loopback requests (`127.0.0.1` / `::1` with no forwarding headers) from per-client rate limits (for local cache warm-up) |

## Deploy

Run with a single worker (`--workers 1`) because rate limits and in-memory event caches live in process memory:

```bash
PORT=8790 EV_RATE_LIMIT_EXEMPT_LOCAL=1 ./deploy/run.sh
```

Warm the disk cache sequentially (30 world cities × 4 NASA POWER variables + 5 showcase events; resumable, backs off on `429`/`503`):

```bash
backend/.venv/bin/python tools/warm_cache.py http://127.0.0.1:8790
```

### Limits & trusted-proxy rule

| Guard | Scope | Limit | Response |
|---|---|---|---|
| Concurrency | `POST /api/check` | 4 in flight | `503` (`busy`) |
| Concurrency | `POST /api/event`, `POST /api/event/profile` | 2 in flight combined | `503` (`busy`) |
| Rate limit (per client) | `POST /api/check` | 10 / 60 s | `429` (`rate_limited`, `Retry-After`) |
| Rate limit (per client) | `POST /api/event`, `POST /api/event/profile` | 4 / 60 s combined | `429` (`rate_limited`, `Retry-After`) |
| Rate limit (per client) | `POST /api/chat` | 5 / 60 s | `429` (`rate_limited`, `Retry-After`) |
| Rate limit (per client) | `POST /api/parse-claim` | 10 / 60 s | `429` (`rate_limited`, `Retry-After`) |
| Shared LLM quota | `/api/chat`, `/api/parse-claim` → Gemini (retries count separately) | 20 / 60 s server-wide | `503` (`llm_unavailable`) |

**Trusted-proxy rule:** `CF-Connecting-IP` (cloudflared) or the right-most `X-Forwarded-For` entry (Tailscale Funnel) is used as the client IP **only** when the TCP peer (`request.client.host`) is loopback (`127.0.0.1` / `::1`); otherwise `request.client.host` is used directly and forwarding headers are ignored. Requests carrying forwarding headers are never exempted by `EV_RATE_LIMIT_EXEMPT_LOCAL`.

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
| POST | `/api/parse-claim` | `{text}` → `{spec, place_found, place_query, notes, model}`: Gemini picks the variable, season, region and direction from fixed lists, the code checks them against the catalog and geocodes the place; no check runs, the user confirms the fields first. `422` `cannot_parse` when no variable fits |
| GET | `/api/grid?variable_id=air_temp&season=JJA` | GeoJSON trend layer for the globe (FDR-corrected); top level has `variable_id`, `start_year`, `end_year`, `pair` (nearest cells with opposite significant trends, or null) and the cell counts `n_cells`, `n_significant_fdr`, `n_significant_raw` (counted from the features when served) |
| GET | `/api/grid/index` | Built trend layers: `[{variable_id, season, start_year, end_year, units_per_decade}]`, read from `data/layers/` |

Each `steps[]` item has `fields` (dot paths into the result that the step summarises) and step-specific fields: `raw` → `n_months`, `monthly`; `season` → `months`, `aggregation`, `years_dropped`; `random_check` → `alpha`, `methods_agree`, `methods_reason`. They are `null` on the other steps.

Errors always look like `{"error": {"code": "...", "message": "..."}}` with codes
`unknown_variable`, `short_series`, `no_data` (the product has no data at this point: ocean, ice,
outside coverage), `bad_request` (400), `place_not_found` (404), `rate_limited` (429),
`internal` (500, details only in the server log), `source_unavailable`, `llm_unavailable`, `busy` (503).
Request bodies over 256 KB get 413 with `bad_request`.

Robustness: the check is repeated on up to 5 periods with the start and/or end shifted by
3–6 years; a window with fewer than 15 valid years does not count. A robust verdict needs
80% of the tested windows, rounded up (5→4, 3→3, 2→2). A 15–17-year period has one window, the
period itself, so stability is reported as "not tested". A series that never changes
(e.g. snow depth in summer) is `not_proven` with reason `no_variation`.

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
