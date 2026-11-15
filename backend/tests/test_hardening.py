"""Offline tests for API hardening: concurrency guards, rate limits, NOAA pool, cache locks, logging, warmup."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
import urllib.error

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app import check as check_mod  # noqa: E402
from app import event as event_mod  # noqa: E402
from app import limits  # noqa: E402
from app import llm  # noqa: E402
from app.check import MainSeries, StationInput  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CaseSpec, ErrorResponse, EventSpec  # noqa: E402
from app.sources import cache, noaa, pollutants  # noqa: E402
import warm_cache  # noqa: E402

client = TestClient(app)

KYIV = {"place_id": "om:703448", "name": "Kyiv, Ukraine", "lat": 50.45, "lon": 30.52}
SASAN = {"place_id": "test:sasan", "name": "Sasan UMPP, India", "lat": 23.98, "lon": 82.63}


def _check_spec(**over):
    s = {
        "claim_text": "Summers in Kyiv are getting hotter",
        "variable_id": "air_temp",
        "place": KYIV,
        "season": "JJA",
        "start_year": 1981,
        "end_year": 2025,
        "claim_direction": "increase",
    }
    s.update(over)
    return s


def _event_spec(**over):
    s = {
        "compound_id": "no2",
        "place": SASAN,
        "event_month": "2015-01",
        "event_label": "Plant opening",
        "window_years": 3,
        "use_control": True,
    }
    s.update(over)
    return s


def _saved_event_payload() -> dict:
    return json.loads((ROOT / "data" / "events" / "sasan-no2.json").read_text(encoding="utf-8"))


# As the facts give it, so the tests follow a data rebuild.
_EFFECT = f"{_saved_event_payload()['effect']:+.3g}"


def _fake_monthly(start=1980, end=2025):
    return [10.0 + 0.05 * (y - start) + (m % 3) * 0.2 for y in range(start, end + 1) for m in range(1, 13)]


@pytest.fixture
def fast_check(monkeypatch: pytest.MonkeyPatch):
    cached = json.loads((ROOT / "data" / "cases" / "kyiv-summer-heat.json").read_text(encoding="utf-8"))
    monkeypatch.setattr("app.main.run_check", lambda spec: cached)


@pytest.fixture
def fast_event(monkeypatch: pytest.MonkeyPatch):
    cached_ev = _saved_event_payload()
    monkeypatch.setattr("app.main.run_event", lambda spec: cached_ev)
    monkeypatch.setattr(
        "app.main.run_event_profile",
        lambda spec: {
            "spec": spec.model_dump(),
            "compound": cached_ev["compound"],
            "site": cached_ev["site"],
            "control": cached_ev["control"],
            "earliest": "2008-01",
            "latest": "2023-01",
            "points": [],
            "provenance": cached_ev["provenance"],
            "meta": cached_ev["meta"],
        },
    )


class _FakeResp:
    def __init__(self, body: str, status: int = 200) -> None:
        self._data = body.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def test_run_script_and_error_models():
    script = ROOT / "deploy" / "run.sh"
    assert script.is_file()
    assert os.access(script, os.X_OK)
    text = script.read_text(encoding="utf-8")
    assert "--workers 1" in text
    assert "--host 127.0.0.1" in text
    assert "8790" in text
    assert "--app-dir" in text

    ErrorResponse.model_validate({"error": {"code": "busy", "message": limits.BUSY_MESSAGE}})
    ErrorResponse.model_validate({"error": {"code": "rate_limited", "message": "Too many requests."}})


def test_anyio_thread_pool_has_40_tokens():
    import anyio

    async def check_tokens():
        return anyio.to_thread.current_default_thread_limiter().total_tokens

    assert anyio.run(check_tokens) == 40


def test_check_concurrency_guard_returns_503_and_releases(monkeypatch: pytest.MonkeyPatch):
    entered = threading.Event()
    release = threading.Event()
    count = 0
    count_lock = threading.Lock()
    monkeypatch.setitem(limits.RATE_LIMITS, "check", (50, 60.0))

    def blocking_check(spec):
        nonlocal count
        with count_lock:
            count += 1
            if count == 4:
                entered.set()
        release.wait(timeout=5.0)
        raise check_mod.CheckError("bad_request", "done")

    monkeypatch.setattr("app.main.run_check", blocking_check)

    results = []
    threads = [threading.Thread(target=lambda: results.append(client.post("/api/check", json=_check_spec()))) for _ in range(4)]
    for t in threads:
        t.start()
    assert entered.wait(timeout=3.0)
    assert limits.check_gate.active == 4

    # 5th concurrent check fails immediately with 503 busy; /health stays responsive.
    t0 = time.monotonic()
    busy_resp = client.post("/api/check", json=_check_spec())
    assert time.monotonic() - t0 < 1.0
    assert busy_resp.status_code == 503
    assert busy_resp.json()["error"]["code"] == "busy"
    assert "busy" in busy_resp.json()["error"]["message"].lower()
    assert client.get("/health").status_code == 200

    release.set()
    for t in threads:
        t.join(timeout=3.0)
    assert len(results) == 4
    assert limits.check_gate.active == 0


def test_event_group_concurrency_guard_shared_between_event_and_profile(monkeypatch: pytest.MonkeyPatch):
    entered = threading.Event()
    release = threading.Event()
    count = 0
    count_lock = threading.Lock()
    monkeypatch.setitem(limits.RATE_LIMITS, "event", (50, 60.0))

    def blocking_event(spec):
        nonlocal count
        with count_lock:
            count += 1
            if count == 2:
                entered.set()
        release.wait(timeout=5.0)
        raise check_mod.CheckError("bad_request", "done")

    monkeypatch.setattr("app.main.run_event", blocking_event)
    monkeypatch.setattr("app.main.run_event_profile", blocking_event)

    t1 = threading.Thread(target=lambda: client.post("/api/event", json=_event_spec()))
    t2 = threading.Thread(target=lambda: client.post("/api/event/profile", json={
        "compound_id": "no2", "place": SASAN, "window_years": 3, "use_control": True
    }))
    t1.start()
    t2.start()
    assert entered.wait(timeout=3.0)
    assert limits.event_gate.active == 2

    busy_event = client.post("/api/event", json=_event_spec())
    busy_prof = client.post("/api/event/profile", json={
        "compound_id": "no2", "place": SASAN, "window_years": 3, "use_control": True
    })
    assert busy_event.status_code == 503 and busy_event.json()["error"]["code"] == "busy"
    assert busy_prof.status_code == 503 and busy_prof.json()["error"]["code"] == "busy"

    release.set()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    assert limits.event_gate.active == 0


def test_concurrency_slot_released_on_exception_and_client_disconnect(monkeypatch: pytest.MonkeyPatch):
    def crash(_spec):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.main.run_check", crash)
    no_raise_client = TestClient(app, raise_server_exceptions=False)
    r = no_raise_client.post("/api/check", json=_check_spec())
    assert r.status_code == 500
    assert limits.check_gate.active == 0

    # Simulate client disconnect (task cancellation) while holding a slot via ASGI.
    started = asyncio.Event()
    gate = limits.ConcurrencyGate(1)

    async def run_cancel():
        async def simulate():
            async with gate.slot():
                started.set()
                await asyncio.sleep(10)

        task = asyncio.create_task(simulate())
        await started.wait()
        assert gate.active == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.active == 0

    asyncio.run(run_cancel())


def test_per_client_rate_limits_and_retry_after(fast_check, fast_event, monkeypatch: pytest.MonkeyPatch):
    # /api/check: 10/min
    for _ in range(10):
        assert client.post("/api/check", json=_check_spec()).status_code == 200
    r_check = client.post("/api/check", json=_check_spec())
    assert r_check.status_code == 429
    assert r_check.json()["error"]["code"] == "rate_limited"
    assert int(r_check.headers["Retry-After"]) >= 1

    # /api/event + /api/event/profile share 4/min
    prof_spec = {"compound_id": "no2", "place": SASAN, "window_years": 3, "use_control": True}
    assert client.post("/api/event", json=_event_spec()).status_code == 200
    assert client.post("/api/event/profile", json=prof_spec).status_code == 200
    assert client.post("/api/event", json=_event_spec(event_month="2016-01")).status_code == 200
    assert client.post("/api/event/profile", json={**prof_spec, "use_control": False}).status_code == 200
    r_event = client.post("/api/event", json=_event_spec())
    assert r_event.status_code == 429
    assert r_event.json()["error"]["code"] == "rate_limited"
    assert int(r_event.headers["Retry-After"]) >= 1

    # /api/chat: 5/min per client (still accepts result from client)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_call_gemini", lambda k, m, p: f"It grew {_EFFECT} units.")
    ev_res = _saved_event_payload()
    for i in range(5):
        r = client.post("/api/chat", json={"kind": "event", "result": ev_res, "question": f"q{i}"})
        assert r.status_code == 200
    r_chat = client.post("/api/chat", json={"kind": "event", "result": ev_res, "question": "q5"})
    assert r_chat.status_code == 429
    assert r_chat.json()["error"]["code"] == "rate_limited"
    assert int(r_chat.headers["Retry-After"]) >= 1


def test_trusted_proxy_headers_and_local_exemption(fast_check, monkeypatch: pytest.MonkeyPatch):
    # Non-loopback peer (TestClient default 'testclient') must IGNORE forwarding headers.
    for i in range(10):
        r = client.post(
            "/api/check",
            json=_check_spec(),
            headers={"CF-Connecting-IP": f"198.51.100.{i}", "X-Forwarded-For": f"203.0.113.{i}"},
        )
        assert r.status_code == 200
    blocked = client.post(
        "/api/check",
        json=_check_spec(),
        headers={"CF-Connecting-IP": "198.51.100.99", "X-Forwarded-For": "203.0.113.99"},
    )
    assert blocked.status_code == 429

    limits.rate_limiter.clear()
    loopback_client = TestClient(app, client=("127.0.0.1", 50000))

    # Loopback peer trusts CF-Connecting-IP (cloudflared) and right-most X-Forwarded-For (Tailscale Funnel).
    for i in range(10):
        assert loopback_client.post(
            "/api/check", json=_check_spec(), headers={"CF-Connecting-IP": "198.51.100.10"}
        ).status_code == 200
    assert loopback_client.post(
        "/api/check", json=_check_spec(), headers={"CF-Connecting-IP": "198.51.100.10"}
    ).status_code == 429
    # Different CF client is unaffected.
    assert loopback_client.post(
        "/api/check", json=_check_spec(), headers={"CF-Connecting-IP": "198.51.100.11"}
    ).status_code == 200

    # Tailscale Funnel: right-most XFF wins; spoofing left-most entry doesn't bypass limit.
    for i in range(10):
        assert loopback_client.post(
            "/api/check", json=_check_spec(), headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.50"}
        ).status_code == 200
    assert loopback_client.post(
        "/api/check", json=_check_spec(), headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.50"}
    ).status_code == 429

    # IPv6 loopback (::1) also trusts forwarding headers.
    v6_client = TestClient(app, client=("::1", 50000))
    assert v6_client.post(
        "/api/check", json=_check_spec(), headers={"X-Forwarded-For": "203.0.113.50"}
    ).status_code == 429

    # EV_RATE_LIMIT_EXEMPT_LOCAL=1 exempts unproxied loopback, NOT proxied loopback.
    limits.rate_limiter.clear()
    monkeypatch.setenv("EV_RATE_LIMIT_EXEMPT_LOCAL", "1")
    for _ in range(15):
        assert loopback_client.post("/api/check", json=_check_spec()).status_code == 200
    for _ in range(10):
        assert loopback_client.post(
            "/api/check", json=_check_spec(), headers={"CF-Connecting-IP": "198.51.100.20"}
        ).status_code == 200
    assert loopback_client.post(
        "/api/check", json=_check_spec(), headers={"CF-Connecting-IP": "198.51.100.20"}
    ).status_code == 429


def test_rate_limiter_bounded_memory():
    rl = limits.RateLimiter(max_keys=5)
    for i in range(25):
        ok, _ = rl.allow("check", f"192.0.2.{i}", 10, 60.0, now=float(i))
        assert ok is True
        assert len(rl._buckets) <= 5

    # Expired buckets at earlier times are pruned automatically.
    rl.clear()
    for i in range(5):
        rl.allow("check", f"10.0.0.{i}", 10, 60.0, now=0.0)
    assert len(rl._buckets) == 5
    rl.allow("check", "10.0.0.99", 10, 60.0, now=61.0)
    assert list(rl._buckets.keys()) == [("check", "10.0.0.99")]


def test_gemini_retry_counts_in_shared_rate_limit(monkeypatch: pytest.MonkeyPatch):
    llm._cache.clear()
    llm._calls.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "RATE_LIMIT", (2, 60.0))

    calls = []

    def fake_gemini(key, model, prompt):
        calls.append(prompt)
        return "Invented 99999" if len(calls) == 1 else f"It grew {_EFFECT} units."

    monkeypatch.setattr(llm, "_call_gemini", fake_gemini)

    ev_res = _saved_event_payload()
    r1 = client.post("/api/chat", json={"kind": "event", "result": ev_res, "question": "first"})
    assert r1.status_code == 200
    assert r1.json()["grounded"] is True
    assert len(calls) == 2
    assert len(llm._calls) == 2

    # Shared Gemini limit (2/min) is now exhausted because the retry counted separately.
    r2 = client.post("/api/chat", json={"kind": "event", "result": ev_res, "question": "second"})
    assert r2.status_code == 503
    assert r2.json()["error"]["code"] == "llm_unavailable"

    # Also verify retry doesn't bypass a limit of 1.
    llm._cache.clear()
    llm._calls.clear()
    calls.clear()
    monkeypatch.setattr(llm, "RATE_LIMIT", (1, 60.0))
    r3 = client.post("/api/chat", json={"kind": "event", "result": ev_res, "question": "third"})
    assert r3.status_code == 503
    assert len(calls) == 1


def test_noaa_daily_parallel_matches_sequential_and_respects_budget(monkeypatch: pytest.MonkeyPatch):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_get_json(url, params=None, **kw):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        try:
            year = int(params["startDate"][:4])
            return [{"DATE": f"{year}-01-{d:02d}", "TAVG": str(year - 2000 + d * 0.01)} for d in range(1, 28)]
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(noaa, "get_json", fake_get_json)
    res = noaa._daily_monthly_series("TEST01", "TAVG", 2001, 2012)
    assert res is not None
    monthly, url = res
    assert max_active > 1 and max_active <= noaa.DAILY_WORKERS
    assert len(monthly) == 12 * 12
    assert "2001-01-01" in url and "2012-12-31" in url
    # Verify exact year ordering (2001 Jan mean = 1.14, 2012 Jan mean = 12.14).
    assert monthly[0] == pytest.approx(1.14)
    assert monthly[11 * 12] == pytest.approx(12.14)

    # Budget expiry: slow fetches abort promptly; the monthly (GSOM) station is kept as it was.
    def slow_get_json(url, params=None, **kw):
        ds = (params or {}).get("dataset")
        if url == noaa.SEARCH_URL:
            return {"results": [{"stations": [{"id": "SLOW1", "name": "SLOW, UA"}],
                                 "boundingPoints": [{"coordinates": [30.52, 50.45]}]}]}
        if ds == "global-summary-of-the-month":
            return []  # < 90% triggers daily fallback
        time.sleep(0.4)
        return []

    monkeypatch.setattr(noaa, "get_json", slow_get_json)
    monkeypatch.setattr(noaa, "DAILY_BUDGET_S", 0.05)

    t0 = time.monotonic()
    st = noaa.best_station(50.45, 30.52, "TAVG", 2015, 2020)
    assert time.monotonic() - t0 < 0.35
    assert st is not None and st.method == "gsom" and st.id == "SLOW1"

    monkeypatch.setattr(
        check_mod,
        "fetch_main_series",
        lambda var, lat, lon, *_: MainSeries(
            monthly=_fake_monthly(), start="1980-01", url="https://power.example/test", retrieved_at="2026-11-15T00:00:00Z"
        ),
    )
    res_check = check_mod.run_check(CaseSpec.model_validate(_check_spec(start_year=2000, end_year=2020)))
    assert res_check.witness is None


def test_cache_per_url_lock_and_event_fixed_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EV_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OFFLINE", raising=False)

    fetch_calls = 0
    fetch_lock = threading.Lock()
    entered = threading.Event()
    proceed = threading.Event()

    def slow_fetch(full, path, src, headers, validate, timeout):
        nonlocal fetch_calls
        with fetch_lock:
            fetch_calls += 1
        entered.set()
        proceed.wait(timeout=3.0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"v": 42}', encoding="utf-8")
        return '{"v": 42}'

    monkeypatch.setattr(cache, "_fetch_and_store", slow_fetch)
    results: list[dict] = []

    t1 = threading.Thread(target=lambda: results.append(cache.get_json("https://example.test/same", {"a": 1})))
    t2 = threading.Thread(target=lambda: results.append(cache.get_json("https://example.test/same", {"a": 1})))
    t1.start()
    assert entered.wait(timeout=2.0)
    t2.start()
    time.sleep(0.05)
    proceed.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert fetch_calls == 1
    assert results == [{"v": 42}, {"v": 42}]
    assert cache._url_locks == {}

    # event._series_locks stays fixed at 64 entries regardless of distinct keys.
    assert len(event_mod._series_locks) == 64
    monkeypatch.setattr(
        event_mod,
        "fetch_event_series",
        lambda c, lat, lon, *, use_control=True: event_mod.EventSeriesInput(
            months=["2020-01"], site=[1.0], control=None, start="2020-01", url="u", retrieved_at="t"
        ),
    )
    comp = event_mod._local_compound("no2")
    for i in range(80):
        event_mod._series(comp, 10.0 + i * 0.01, 20.0, False)
    assert len(event_mod._series_locks) == 64
    assert len(event_mod._series_cache) <= event_mod.SERIES_CACHE_SIZE


def test_request_logging_cache_vs_network_including_worker_pools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setenv("EV_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.setattr(check_mod, "fetch_station", lambda *a, **k: None)

    power_raw = (ROOT / "backend" / "tests" / "fixtures" / "sources" / "power_kyiv_1981_1983.json").read_text()
    power_data = json.loads(power_raw)
    t2m = power_data["properties"]["parameter"]["T2M"]
    for y in range(1980, 2026):
        for m in range(1, 13):
            t2m.setdefault(f"{y}{m:02d}", 10.0 + 0.05 * (y - 1980))

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=30: _FakeResp(json.dumps(power_data)),
    )

    caplog.set_level(logging.INFO, logger="ev")
    caplog.clear()
    r1 = client.post("/api/check", json=_check_spec())
    assert r1.status_code == 200
    recs1 = [r.message for r in caplog.records if r.name == "ev"]
    assert len(recs1) == 1
    assert "POST" in recs1[0] and "/api/check" in recs1[0] and "200" in recs1[0]
    assert "ms" in recs1[0] and recs1[0].endswith("network")

    # Second identical check hits disk cache -> logs 'cache'.
    caplog.clear()
    r2 = client.post("/api/check", json=_check_spec())
    assert r2.status_code == 200
    recs2 = [r.message for r in caplog.records if r.name == "ev"]
    assert len(recs2) == 1 and recs2[0].endswith("cache")

    # Worker-pool fetches inside pollutants.fetch_site_and_control propagate contextvars -> 'network'.
    monkeypatch.setenv("EARTHDATA_TOKEN", "tok")
    csv_body = "prod_name,OMNO2d\nunit,x\nundef,-999\nlat,10\nlon,10\n\nTimestamp (UTC),Data\n2005-01-01 00:00,1e15\n"
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=30: _FakeResp(csv_body))
    caplog.clear()
    r_ev = client.post("/api/event", json=_event_spec(use_control=False))
    assert r_ev.status_code == 200
    recs3 = [r.message for r in caplog.records if r.name == "ev"]
    assert len(recs3) == 1 and "/api/event" in recs3[0] and recs3[0].endswith("network")


def test_warm_cache_tool_builds_tasks_backs_off_and_resumes(tmp_path: Path):
    tasks = warm_cache.build_tasks(ROOT / "data" / "events")
    check_tasks = [t for t in tasks if t.path == "/api/check"]
    event_tasks = [t for t in tasks if t.path == "/api/event"]
    assert len(warm_cache.CITIES) == 30
    assert len(check_tasks) == 30 * 4
    assert len(event_tasks) == 5
    for t in check_tasks:
        CaseSpec.model_validate(t.payload)
    for t in event_tasks:
        EventSpec.model_validate(t.payload)

    # Exercise backoff (429 + 503) and resumability on a small synthetic events dir.
    ev_dir = tmp_path / "events"
    ev_dir.mkdir()
    ev_data = _saved_event_payload()
    (ev_dir / "one.json").write_text(json.dumps(ev_data), encoding="utf-8")
    state_file = tmp_path / "state.json"

    calls: list[str] = []
    sleeps: list[float] = []
    attempts_for_first = 0

    geocoded = {"place_id": "om:1", "name": "Kyiv, Ukraine", "lat": 50.45466, "lon": 30.5238}
    sent_places: list[dict] = []

    def fake_urlopen(req, timeout=180.0):
        nonlocal attempts_for_first
        if "/api/places?" in req.full_url:
            return _FakeResp(json.dumps([geocoded] if "q=Kyiv" in req.full_url else []), status=200)
        calls.append(req.full_url)
        if req.full_url.endswith("/api/check"):
            sent_places.append(json.loads(req.data)["place"])
        if len(calls) == 1:
            attempts_for_first += 1
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "3"}, io.BytesIO(b""))
        if len(calls) == 2:
            raise urllib.error.HTTPError(req.full_url, 503, "Busy", {}, io.BytesIO(b""))
        return _FakeResp('{"ok": true}', status=200)

    ok, skipped, failed = warm_cache.warm(
        "http://127.0.0.1:8790",
        state_path=state_file,
        events_dir=ev_dir,
        sleep_fn=sleeps.append,
        urlopen_fn=fake_urlopen,
    )
    assert ok == 121 and skipped == 0 and failed == 0
    assert sleeps == [3.5, 10.0]
    assert len(calls) == 123
    # The geocoder's coordinates are sent (they key the caches); unknown names keep the built-in point.
    assert geocoded in sent_places
    assert any(p["place_id"].startswith("warm:") for p in sent_places)

    # Re-running skips all 121 already-completed tasks with zero HTTP requests.
    calls.clear()
    ok2, skipped2, failed2 = warm_cache.warm(
        "http://127.0.0.1:8790",
        state_path=state_file,
        events_dir=ev_dir,
        sleep_fn=sleeps.append,
        urlopen_fn=fake_urlopen,
    )
    assert (ok2, skipped2, failed2) == (0, 121, 0)
    assert calls == []


@pytest.mark.parametrize("host, loopback", [("100.112.83.120", False), ("10.0.0.5", False), ("127.0.0.2", True),
                                            ("::1", True), ("::ffff:127.0.0.1", True), ("2001:db8::1", False), ("testclient", False)])
def test_loopback_check_handles_every_address_kind(host, loopback):
    from app import limits
    assert limits._is_loopback(host) is loopback
