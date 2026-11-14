"""Earth Verdict HTTP API.

Run (from repo root):
  backend/.venv/bin/uvicorn app.main:app --app-dir backend --reload
The frontend dev server proxies /api to http://127.0.0.1:8000.
"""
from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .catalog import load_compounds, load_variables
from .check import REGIONS, CheckError, run_check
from .llm import explain
from .event import get_global_co2_summary, run_co2_impact, run_event
from .models import (
    CaseSpec,
    ChatRequest,
    ChatResponse,
    CheckResult,
    Co2GlobalSummary,
    Co2ImpactResult,
    Co2ImpactSpec,
    Compound,
    ErrorResponse,
    EventResult,
    EventSpec,
    Place,
    Variable,
)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("EV_DATA_DIR", ROOT / "data"))
CASES_DIR = DATA_DIR / "cases"
EVENTS_DIR = DATA_DIR / "events"
LAYERS_DIR = DATA_DIR / "layers"
FRONTEND_DIST = ROOT / "frontend" / "dist"

STATUS = {"bad_request": 400, "short_series": 400, "unknown_variable": 400,
          "place_not_found": 404, "source_unavailable": 503, "llm_unavailable": 503}

app = FastAPI(title="Earth Verdict API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("EV_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def error(code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error={"code": code, "message": message}).model_dump()
    return JSONResponse(body, status_code=STATUS.get(code, 400))


@app.exception_handler(CheckError)
async def _check_error(_: Request, exc: CheckError):
    return error(exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return error("bad_request", f"Invalid request{f' ({where})' if where else ''}: {first.get('msg', 'bad input')}.")


@app.get("/health")
async def health():
    return {"status": "ok", "offline": os.environ.get("OFFLINE") == "1"}


@app.get("/api/variables", response_model=list[Variable])
async def variables():
    return [v.public() for v in load_variables().values()]


@app.get("/api/places", response_model=list[Place], responses={503: {"model": ErrorResponse}})
async def places(q: str = Query("", max_length=100)):
    if len(q.strip()) < 2:
        return []
    from .sources import SourceUnavailable, geocode

    regions = [Place(place_id=f"region:{k}", name=name, lat=lat, lon=lon)
               for k, (name, lat, lon) in REGIONS.items()
               if name.lower().startswith(q.strip().lower()) or k.startswith(q.strip().lower().replace(" ", ""))
               or (k == "globe" and q.strip().lower() in ("world", "planet", "earth", "globe"))]

    try:
        found = await asyncio.to_thread(geocode.search_places, q.strip())
    except SourceUnavailable as e:
        if regions:
            return regions
        return error("source_unavailable", f"Place search did not respond: {e.message}")
    return regions + [Place(place_id=p["place_id"], name=p["name"], lat=p["lat"], lon=p["lon"]) for p in found]


@app.post("/api/check", response_model=CheckResult,
          responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def check(spec: CaseSpec):
    return await asyncio.to_thread(run_check, spec)


# ---------- showcase cases (work offline) ----------

@lru_cache(maxsize=1)
def _case_index() -> dict[str, Path]:
    return {p.stem: p for p in sorted(CASES_DIR.glob("*.json")) if p.stem != "mock"}


@app.get("/api/cases")
async def cases():
    out = []
    for cid, path in _case_index().items():
        r = json.loads(path.read_text())
        out.append({"id": cid, "claim_text": r["case"]["claim_text"], "place": r["case"]["place"]["name"],
                    "variable_id": r["case"]["variable_id"], "verdict": r["verdict"]})
    return out


@app.get("/api/cases/{case_id}", response_model=CheckResult, responses={404: {"model": ErrorResponse}})
async def case(case_id: str):
    path = _case_index().get(case_id)
    if path is None:
        return JSONResponse(ErrorResponse(error={"code": "bad_request",
                                                 "message": f"Unknown case '{case_id}'."}).model_dump(),
                            status_code=404)
    return JSONResponse(json.loads(path.read_text()))


# ---------- pollutant event impact & CO2 physics ----------

@app.get("/api/compounds", response_model=list[Compound])
async def compounds():
    return [c.public() for c in load_compounds().values()]


@app.post("/api/event", response_model=EventResult,
          responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def event(spec: EventSpec):
    return await asyncio.to_thread(run_event, spec)


def _event_index() -> dict[str, Path]:
    if not EVENTS_DIR.is_dir():
        return {}
    return {p.stem: p for p in sorted(EVENTS_DIR.glob("*.json"))}


@app.get("/api/events")
async def events():
    out = []
    for eid, path in _event_index().items():
        r = json.loads(path.read_text())
        out.append({
            "id": eid,
            "event_label": r["spec"]["event_label"],
            "event_month": r["spec"]["event_month"],
            "place": r["spec"]["place"]["name"],
            "compound_id": r["spec"]["compound_id"],
            "verdict": r["verdict"],
            "reason": r["reason"],
            "effect": r["effect"],
            "relative_change": r["relative_change"],
        })
    return out


@app.get("/api/events/{event_id}", response_model=EventResult, responses={404: {"model": ErrorResponse}})
async def event_detail(event_id: str):
    path = _event_index().get(event_id)
    if path is None:
        return JSONResponse(ErrorResponse(error={"code": "bad_request",
                                                 "message": f"Unknown event '{event_id}'."}).model_dump(),
                            status_code=404)
    return JSONResponse(json.loads(path.read_text()))


@app.post("/api/co2-impact", response_model=Co2ImpactResult,
          responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def co2_impact(spec: Co2ImpactSpec):
    return await asyncio.to_thread(run_co2_impact, spec)


@app.get("/api/co2/global", response_model=Co2GlobalSummary,
         responses={503: {"model": ErrorResponse}})
async def co2_global():
    summary, _ = await asyncio.to_thread(get_global_co2_summary)
    return summary


# ---------- plain-language explanation / follow-up questions (Gemini) ----------

@app.post("/api/chat", response_model=ChatResponse,
          responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def chat(req: ChatRequest):
    try:
        return await asyncio.to_thread(explain, req.kind, req.result, req.question, req.lang)
    except ValidationError as exc:
        return error("bad_request", f"'result' is not a valid {req.kind} result: {exc.errors()[0]['msg']}.")


# ---------- trend layers for the globe (precomputed, FDR-corrected) ----------

@app.get("/api/grid")
async def grid(variable_id: Literal["air_temp", "precip"] = "air_temp",
               season: Literal["year", "JJA", "DJF"] = "JJA"):
    param = {"air_temp": "T2M", "precip": "PRECTOTCORR"}[variable_id]
    path = LAYERS_DIR / f"trends_{param}_{season}.geojson"
    if not path.exists():
        return JSONResponse(ErrorResponse(error={"code": "source_unavailable",
                                                 "message": "This trend layer has not been built yet."}).model_dump(),
                            status_code=503)
    return FileResponse(path, media_type="application/geo+json")


# ---------- built frontend (single-service deploy) ----------

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
