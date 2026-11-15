#!/usr/bin/env python3
"""Sequential, resumable cache warm-up client for the running Earth Verdict API.

Warms 30 major world cities x 4 global NASA POWER variables (/api/check) and the
5 showcase events from data/events/*.json (/api/event).

If the server runs with EV_RATE_LIMIT_EXEMPT_LOCAL=1, loopback requests without
forwarding headers skip per-client rate limits; otherwise this script automatically
backs off on HTTP 429 (honoring Retry-After) and HTTP 503.

Run (from repository root):
  backend/.venv/bin/python tools/warm_cache.py --base-url http://127.0.0.1:8790
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import time
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "http://127.0.0.1:8790"

# 4 global NASA POWER variables from backend/app/catalog/variables.yaml
WARM_VARIABLES: tuple[tuple[str, int, int], ...] = (
    ("air_temp", 1981, 2025),
    ("precip", 1981, 2025),
    ("soil_moisture", 1981, 2025),
    ("sunlight", 1984, 2025),
)

CITIES: tuple[dict, ...] = (
    {"place_id": "warm:kyiv", "name": "Kyiv, Ukraine", "lat": 50.4501, "lon": 30.5234},
    {"place_id": "warm:lviv", "name": "Lviv, Ukraine", "lat": 49.8397, "lon": 24.0297},
    {"place_id": "warm:warsaw", "name": "Warsaw, Poland", "lat": 52.2297, "lon": 21.0122},
    {"place_id": "warm:london", "name": "London, United Kingdom", "lat": 51.5074, "lon": -0.1278},
    {"place_id": "warm:paris", "name": "Paris, France", "lat": 48.8566, "lon": 2.3522},
    {"place_id": "warm:berlin", "name": "Berlin, Germany", "lat": 52.5200, "lon": 13.4050},
    {"place_id": "warm:madrid", "name": "Madrid, Spain", "lat": 40.4168, "lon": -3.7038},
    {"place_id": "warm:rome", "name": "Rome, Italy", "lat": 41.9028, "lon": 12.4964},
    {"place_id": "warm:istanbul", "name": "Istanbul, Turkey", "lat": 41.0082, "lon": 28.9784},
    {"place_id": "warm:cairo", "name": "Cairo, Egypt", "lat": 30.0444, "lon": 31.2357},
    {"place_id": "warm:lagos", "name": "Lagos, Nigeria", "lat": 6.5244, "lon": 3.3792},
    {"place_id": "warm:nairobi", "name": "Nairobi, Kenya", "lat": -1.2921, "lon": 36.8219},
    {"place_id": "warm:johannesburg", "name": "Johannesburg, South Africa", "lat": -26.2041, "lon": 28.0473},
    {"place_id": "warm:mumbai", "name": "Mumbai, India", "lat": 19.0760, "lon": 72.8777},
    {"place_id": "warm:delhi", "name": "Delhi, India", "lat": 28.6139, "lon": 77.2090},
    {"place_id": "warm:beijing", "name": "Beijing, China", "lat": 39.9042, "lon": 116.4074},
    {"place_id": "warm:shanghai", "name": "Shanghai, China", "lat": 31.2304, "lon": 121.4737},
    {"place_id": "warm:tokyo", "name": "Tokyo, Japan", "lat": 35.6762, "lon": 139.6503},
    {"place_id": "warm:seoul", "name": "Seoul, South Korea", "lat": 37.5665, "lon": 126.9780},
    {"place_id": "warm:bangkok", "name": "Bangkok, Thailand", "lat": 13.7563, "lon": 100.5018},
    {"place_id": "warm:singapore", "name": "Singapore, Singapore", "lat": 1.3521, "lon": 103.8198},
    {"place_id": "warm:jakarta", "name": "Jakarta, Indonesia", "lat": -6.2088, "lon": 106.8456},
    {"place_id": "warm:sydney", "name": "Sydney, Australia", "lat": -33.8688, "lon": 151.2093},
    {"place_id": "warm:melbourne", "name": "Melbourne, Australia", "lat": -37.8136, "lon": 144.9631},
    {"place_id": "warm:new-york", "name": "New York, United States", "lat": 40.7128, "lon": -74.0060},
    {"place_id": "warm:los-angeles", "name": "Los Angeles, United States", "lat": 34.0522, "lon": -118.2437},
    {"place_id": "warm:chicago", "name": "Chicago, United States", "lat": 41.8781, "lon": -87.6298},
    {"place_id": "warm:mexico-city", "name": "Mexico City, Mexico", "lat": 19.4326, "lon": -99.1332},
    {"place_id": "warm:sao-paulo", "name": "Sao Paulo, Brazil", "lat": -23.5505, "lon": -46.6333},
    {"place_id": "warm:buenos-aires", "name": "Buenos Aires, Argentina", "lat": -34.6037, "lon": -58.3816},
)


@dataclass(frozen=True)
class WarmTask:
    key: str
    label: str
    path: str
    payload: dict
    city: dict | None = None    # check tasks: resolved through /api/places just before sending


def default_data_dir() -> Path:
    env = os.environ.get("EV_DATA_DIR", "").strip()
    return Path(env) if env else ROOT / "data"


def default_state_path() -> Path:
    return default_data_dir() / "cache" / "warm_cache_state.json"


def resolve_place(base_url: str, city: dict, *, timeout: float = 30.0, urlopen_fn=urllib.request.urlopen) -> dict:
    """The place the frontend would send: the first /api/places result for the city's name.

    Caches are keyed by coordinates (NASA POWER rounds to 4 decimals), so warming the geocoder's
    coordinates is what makes a visitor's first check fast. Falls back to the built-in point.
    """
    q = city["name"].split(",")[0]
    url = base_url.rstrip("/") + "/api/places?" + urllib.parse.urlencode({"q": q})
    try:
        with urlopen_fn(urllib.request.Request(url), timeout=timeout) as resp:
            found = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return city
    places = [p for p in found if isinstance(p, dict) and not str(p.get("place_id", "")).startswith("region:")]
    return places[0] if places else city


def build_tasks(events_dir: Path | None = None) -> list[WarmTask]:
    """Build the 120 city-variable check tasks and 5 showcase event tasks."""
    tasks: list[WarmTask] = []
    for city in CITIES:
        for var_id, start_year, end_year in WARM_VARIABLES:
            tasks.append(
                WarmTask(
                    key=f"check:{city['place_id']}:{var_id}:{start_year}:{end_year}",
                    label=f"check {city['name']} [{var_id}]",
                    path="/api/check",
                    payload={
                        "claim_text": f"Cache warm-up: {var_id} in {city['name']}",
                        "variable_id": var_id,
                        "place": city,
                        "season": "year",
                        "start_year": start_year,
                        "end_year": end_year,
                        "claim_direction": "change",
                    },
                    city=city,
                )
            )

    ev_dir = events_dir or (ROOT / "data" / "events")
    if ev_dir.is_dir():
        for path in sorted(p for p in ev_dir.glob("*.json") if not p.stem.startswith("_")):
            data = json.loads(path.read_text(encoding="utf-8"))
            spec = data["spec"]
            tasks.append(
                WarmTask(
                    key=f"event:{path.stem}",
                    label=f"event {path.stem} ({spec['compound_id']})",
                    path="/api/event",
                    payload=spec,
                )
            )
    return tasks


def load_state(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("completed", []))
    except (ValueError, OSError):
        return set()


def save_state(path: Path, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"completed": sorted(completed)}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _retry_after_s(headers, default: float = 60.0) -> float:
    raw = headers.get("Retry-After") if headers else None
    if not raw:
        return default
    try:
        return max(1.0, float(raw))
    except ValueError:
        return default


def post_with_backoff(
    base_url: str,
    task: WarmTask,
    *,
    timeout: float = 180.0,
    max_retries: int = 5,
    sleep_fn: Callable[[float], None] = time.sleep,
    urlopen_fn=urllib.request.urlopen,
) -> tuple[bool, str]:
    """POST one warm-up payload, backing off on 429/503/transient errors."""
    url = base_url.rstrip("/") + task.path
    body = json.dumps(task.payload).encode("utf-8")
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen_fn(req, timeout=timeout) as resp:
                resp.read()
                return True, f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if exc.code == 429 and attempt < max_retries:
                wait_s = _retry_after_s(exc.headers) + 0.5
                print(f"    rate-limited (429), sleeping {wait_s:.1f}s...", flush=True)
                sleep_fn(wait_s)
                continue
            if exc.code == 503 and attempt < max_retries:
                wait_s = min(60.0, 5.0 * (2**attempt))
                print(f"    service busy/unavailable (503), sleeping {wait_s:.1f}s...", flush=True)
                sleep_fn(wait_s)
                continue
            return False, f"HTTP {exc.code}: {detail or exc.reason}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < max_retries:
                wait_s = min(60.0, 5.0 * (2**attempt))
                print(f"    transient error ({exc}), sleeping {wait_s:.1f}s...", flush=True)
                sleep_fn(wait_s)
                continue
            return False, str(exc)
    return False, "exhausted retries"


def warm(
    base_url: str = DEFAULT_BASE_URL,
    *,
    state_path: Path | None = None,
    events_dir: Path | None = None,
    reset: bool = False,
    delay: float = 0.0,
    timeout: float = 180.0,
    max_retries: int = 5,
    sleep_fn: Callable[[float], None] = time.sleep,
    urlopen_fn=urllib.request.urlopen,
) -> tuple[int, int, int]:
    """Run all warm-up tasks sequentially, returning (ok, skipped, failed)."""
    state_file = state_path or default_state_path()
    completed = set() if reset else load_state(state_file)
    tasks = build_tasks(events_dir=events_dir)
    places: dict[str, dict] = {}
    total = len(tasks)
    ok_count = 0
    skip_count = 0
    fail_count = 0

    for idx, task in enumerate(tasks, start=1):
        if task.key in completed:
            skip_count += 1
            print(f"[{idx}/{total}] {task.label} ... skip (already OK)", flush=True)
            continue

        if task.city is not None:
            pid = task.city["place_id"]
            if pid not in places:
                places[pid] = resolve_place(base_url, task.city, urlopen_fn=urlopen_fn)
            task = WarmTask(task.key, task.label, task.path, {**task.payload, "place": places[pid]}, task.city)

        t0 = time.monotonic()
        ok, info = post_with_backoff(
            base_url,
            task,
            timeout=timeout,
            max_retries=max_retries,
            sleep_fn=sleep_fn,
            urlopen_fn=urlopen_fn,
        )
        dt = time.monotonic() - t0
        if ok:
            ok_count += 1
            completed.add(task.key)
            save_state(state_file, completed)
            print(f"[{idx}/{total}] {task.label} ... OK ({dt:.1f}s)", flush=True)
        else:
            fail_count += 1
            print(f"[{idx}/{total}] {task.label} ... FAIL ({info})", flush=True)

        if delay > 0 and idx < total:
            sleep_fn(delay)

    print(f"Done: {ok_count} warmed, {skip_count} skipped, {fail_count} failed (total {total}).", flush=True)
    return ok_count, skip_count, fail_count


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Warm the Earth Verdict HTTP cache sequentially.")
    ap.add_argument("url", nargs="?", default=None, help=f"API base URL (default: {DEFAULT_BASE_URL})")
    ap.add_argument("--base-url", dest="base_url", default=None, help="API base URL (overrides positional url)")
    ap.add_argument("--state", type=Path, default=None, help="Resumable state JSON path")
    ap.add_argument("--reset", action="store_true", help="Ignore prior warm-up state and run all tasks")
    ap.add_argument("--delay", type=float, default=0.0, help="Polite pause in seconds between requests (default: 0)")
    ap.add_argument("--timeout", type=float, default=180.0, help="Per-request HTTP timeout in seconds")
    ap.add_argument("--max-retries", type=int, default=5, help="Max retries on 429/503/network errors")
    args = ap.parse_args(argv)

    base_url = args.base_url or args.url or DEFAULT_BASE_URL
    _, _, failed = warm(
        base_url,
        state_path=args.state,
        reset=args.reset,
        delay=args.delay,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
