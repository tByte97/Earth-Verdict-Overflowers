"""Earth Verdict HTTP API.

Run (from repo root):
  backend/.venv/bin/uvicorn app.main:app --app-dir backend --reload
The frontend dev server proxies /api to http://127.0.0.1:8000.
"""
from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

import anyio
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .catalog import load_compounds, load_variables
from .check import REGIONS, CheckError, run_check
from .event import get_global_co2_summary, list_event_sites, run_co2_impact, run_event, run_event_profile
from .limits import BusyError, RateLimitError, check_gate, concurrency_guard, event_gate, rate_guard
from .llm import explain
from .parse import parse_claim
from .sources.cache import track_network_fetches
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
    EventProfile,
    EventProfileSpec,
    EventResult,
    EventSite,
    EventSpec,
    ParsedClaim,
    ParseRequest,
    Place,
    Variable,
)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("EV_DATA_DIR", ROOT / "data"))
CASES_DIR = DATA_DIR / "cases"
EVENTS_DIR = DATA_DIR / "events"
LAYERS_DIR = DATA_DIR / "layers"
FRONTEND_DIST = ROOT / "frontend" / "dist"

STATUS = {"bad_request": 400, "cannot_parse": 422, "short_series": 400, "unknown_variable": 400, "no_data": 400,
          "place_not_found": 404, "rate_limited": 429, "internal": 500,
          "source_unavailable": 503, "llm_unavailable": 503, "busy": 503}

MAX_BODY_BYTES = 256 * 1024

logger = logging.getLogger("ev")
logger.setLevel(logging.INFO)
log = logger


class BodyLimit:
    """Reject request bodies over `max_bytes` with 413, counting the bytes actually received.

    Content-Length alone is not enough: a chunked request has none. Bodies here are small JSON
    specs, so the body is buffered once and replayed to the app.
    """

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_bytes:
            await self._too_large(scope, receive, send)
            return
        chunks, size, more = [], 0, True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await self._too_large(scope, receive, send)
                return
            chunks.append(chunk)
            more = message.get("more_body", False)

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay, send)

    async def _too_large(self, scope, receive, send):
        body = ErrorResponse(error={"code": "bad_request",
                                    "message": f"Request body is larger than {self.max_bytes // 1024} KB."})
        await JSONResponse(body.model_dump(), status_code=413)(scope, receive, send)


class InternalErrorMiddleware:
    """Catch unhandled HTTP exceptions inside CORSMiddleware so 500s still carry CORS headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def _send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope.get("method", "?"), scope.get("path", "?"))
            if response_started:
                raise
            await error("internal", "Something went wrong on our side. Try again or open a saved case.")(
                scope, receive, send
            )


class RequestLogMiddleware:
    """Emit one log line per request: method, route, status, duration ms, cache/network."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        with track_network_fetches() as counter:
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000.0
                route_obj = scope.get("route")
                route = getattr(route_obj, "path", None) or scope.get("path", "")
                source = "network" if counter.count > 0 else "cache"
                if not log.handlers and not logging.getLogger().handlers:
                    handler = logging.StreamHandler()
                    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
                    log.addHandler(handler)
                log.info("%s %s %d %.1fms %s", scope.get("method", ""), route, status_code, duration_ms, source)


app = FastAPI(title="Earth Verdict API", version="0.1.0")
app.add_middleware(BodyLimit)   # added before CORS, so a 413 still carries CORS headers
app.add_middleware(InternalErrorMiddleware)   # also inside CORS, so a 500 still carries CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("EV_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.add_middleware(RequestLogMiddleware)


def error(code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error={"code": code, "message": message}).model_dump()
    return JSONResponse(body, status_code=STATUS.get(code, 400))


@app.exception_handler(BusyError)
async def _busy_error(_: Request, exc: BusyError):
    return error("busy", exc.message)


@app.exception_handler(RateLimitError)
async def _rate_limit_error(_: Request, exc: RateLimitError):
    resp = error("rate_limited", exc.message)
    resp.headers["Retry-After"] = str(exc.retry_after)
    return resp


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
        found = await anyio.to_thread.run_sync(geocode.search_places, q.strip())
    except SourceUnavailable as e:
        if regions:
            return regions
        return error("source_unavailable", f"Place search did not respond: {e.message}")
    return regions + [Place(place_id=p["place_id"], name=p["name"], lat=p["lat"], lon=p["lon"]) for p in found]


@app.post("/api/check", response_model=CheckResult,
          dependencies=[Depends(rate_guard("check")), Depends(concurrency_guard(check_gate))],
          responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def check(spec: CaseSpec):
    return await anyio.to_thread.run_sync(run_check, spec)


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
          dependencies=[Depends(rate_guard("event")), Depends(concurrency_guard(event_gate))],
          responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def event(spec: EventSpec):
    return await anyio.to_thread.run_sync(run_event, spec)


@app.post("/api/event/profile", response_model=EventProfile,
          dependencies=[Depends(rate_guard("event")), Depends(concurrency_guard(event_gate))],
          responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def event_profile(spec: EventProfileSpec):
    return await anyio.to_thread.run_sync(run_event_profile, spec)


@app.get("/api/event-sites", response_model=list[EventSite])
async def event_sites():
    return list_event_sites(set(_event_index()))


def _event_index() -> dict[str, Path]:
    if not EVENTS_DIR.is_dir():
        return {}
    return {p.stem: p for p in sorted(EVENTS_DIR.glob("*.json")) if not p.stem.startswith("_")}


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
    return await anyio.to_thread.run_sync(run_co2_impact, spec)


@app.get("/api/co2/global", response_model=Co2GlobalSummary,
         responses={503: {"model": ErrorResponse}})
async def co2_global():
    summary, _ = await anyio.to_thread.run_sync(get_global_co2_summary)
    return summary


# ---------- plain-language explanation / follow-up questions (Gemini) ----------

@app.post("/api/chat", response_model=ChatResponse,
          dependencies=[Depends(rate_guard("chat"))],
          responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def chat(req: ChatRequest):
    try:
        return await anyio.to_thread.run_sync(explain, req.kind, req.result, req.question, req.lang)
    except ValidationError as exc:
        return error("bad_request", f"'result' is not a valid {req.kind} result: {exc.errors()[0]['msg']}.")


@app.post("/api/parse-claim", response_model=ParsedClaim,
          dependencies=[Depends(rate_guard("parse"))],
          responses={422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def parse(req: ParseRequest):
    """Free text -> check parameters for the user to confirm. No check runs here."""
    return await anyio.to_thread.run_sync(parse_claim, req.text)


# ---------- trend layers for the globe (precomputed, FDR-corrected) ----------

LAYER_INDEX_KEYS = ("variable_id", "season", "start_year", "end_year", "units_per_decade")


@lru_cache(maxsize=32)
def _read_layer(path: Path, mtime_ns: int) -> dict:
    """Layer file plus cell counts taken from its features (the files predate the counts)."""
    layer = json.loads(path.read_text(encoding="utf-8"))
    props = [f["properties"] for f in layer["features"]]
    head = {k: v for k, v in layer.items() if k != "features"}
    # n_cells counts tested cells only (a cell too short for the test has p = null and is not in the FDR).
    return {**head, "n_cells": sum(p.get("p") is not None for p in props),
            "n_significant_fdr": sum(bool(p.get("significant_fdr")) for p in props),
            "n_significant_raw": sum(bool(p.get("significant_raw")) for p in props),
            "features": layer["features"]}


def load_layer(path: Path) -> dict:
    return _read_layer(path, path.stat().st_mtime_ns)


@app.get("/api/grid/index")
async def grid_index():
    """Layers that are actually built, read from LAYERS_DIR."""
    return [{k: load_layer(path)[k] for k in LAYER_INDEX_KEYS}
            for path in sorted(LAYERS_DIR.glob("trends_*.geojson"))]


@app.get("/api/grid")
async def grid(variable_id: Literal["air_temp", "precip"] = "air_temp",
               season: Literal["year", "JJA", "DJF"] = "JJA"):
    param = {"air_temp": "T2M", "precip": "PRECTOTCORR"}[variable_id]
    path = LAYERS_DIR / f"trends_{param}_{season}.geojson"
    if not path.exists():
        return JSONResponse(ErrorResponse(error={"code": "source_unavailable",
                                                 "message": "This trend layer has not been built yet."}).model_dump(),
                            status_code=503)
    return JSONResponse(load_layer(path), media_type="application/geo+json")


# ---------- built frontend (single-service deploy) ----------

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
