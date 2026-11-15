"""File-backed HTTP cache and retry layer using stdlib urllib."""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .errors import SourceUnavailable

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_UA = {"User-Agent": "Mozilla/5.0 (EarthVerdict hackathon fetcher)"}
_RETRIES = 2
_DEFAULT_TIMEOUT_S = 30.0

_url_locks: dict[str, list] = {}
_url_guard = threading.Lock()


class _FetchCounter:
    """Thread-safe counter for network fetches performed during one request."""

    __slots__ = ("count", "_lock")

    def __init__(self) -> None:
        self.count = 0
        self._lock = threading.Lock()

    def inc(self) -> None:
        with self._lock:
            self.count += 1


_network_fetches: contextvars.ContextVar[_FetchCounter | None] = contextvars.ContextVar(
    "ev_network_fetches",
    default=None,
)


@contextlib.contextmanager
def track_network_fetches():
    """Track how many network downloads happen within the active context."""
    counter = _FetchCounter()
    token = _network_fetches.set(counter)
    try:
        yield counter
    finally:
        _network_fetches.reset(token)


def _record_network_fetch() -> None:
    counter = _network_fetches.get()
    if counter is not None:
        counter.inc()


@contextlib.contextmanager
def _url_lock(key: str):
    """Per-URL mutex with refcounted cleanup so in-flight URLs don't leak memory."""
    with _url_guard:
        entry = _url_locks.get(key)
        if entry is None:
            entry = [threading.Lock(), 0]
            _url_locks[key] = entry
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _url_guard:
            entry[1] -= 1
            if entry[1] == 0:
                _url_locks.pop(key, None)


def data_dir() -> Path:
    """Return the root data directory, overridden by EV_DATA_DIR if set."""
    env = os.environ.get("EV_DATA_DIR", "").strip()
    return Path(env) if env else _DEFAULT_DATA_DIR


def cache_dir() -> Path:
    """Return the HTTP cache directory under the active data directory."""
    return data_dir() / "cache"


def _is_offline() -> bool:
    return os.environ.get("OFFLINE", "").strip().lower() in ("1", "true", "yes")


def source_name(url: str) -> str:
    """Derive a canonical source identifier from a request URL."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "power.larc.nasa.gov" in host or host.startswith("power."):
        return "power"
    if "giovanni" in host:
        return "giovanni"
    if "open-meteo" in host:
        return "open-meteo"
    if "ncei.noaa.gov" in host or "noaa" in host:
        if "climate-at-a-glance" in path:
            return "cag"
        return "noaa"
    return host or "unknown"


def build_url(url: str, params: dict | None = None) -> str:
    """Construct full request URL using the same encoding as tools/fetch_data.py."""
    return url + ("?" + urllib.parse.urlencode(params) if params else "")


def cache_path(full_url: str, ext: str = "json") -> Path:
    """Compute cache file path from full URL (without headers or tokens)."""
    key = hashlib.sha1(full_url.encode()).hexdigest()[:16]
    return cache_dir() / f"{key}.{ext}"


def _read_if_fresh(path: Path, *, refresh: bool, max_age_s: float | None) -> tuple[str | None, bool]:
    if not path.exists() or refresh:
        return None, False
    stale = max_age_s is not None and time.time() - path.stat().st_mtime > max_age_s
    if not stale or _is_offline():
        return path.read_text(encoding="utf-8"), stale
    return None, True


def get_text(
    url: str,
    params: dict | None = None,
    *,
    headers: dict | None = None,
    ext: str = "json",
    refresh: bool = False,
    validate: Callable[[str], Any] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
    max_age_s: float | None = None,
) -> str:
    """Fetch URL text with file caching, offline support, and retries with backoff.

    With ``max_age_s``, a cached copy older than that is refetched; if the refetch fails, the
    stale copy is returned instead of an error.
    """
    full = build_url(url, params)
    path = cache_path(full, ext=ext)
    cached, stale = _read_if_fresh(path, refresh=refresh, max_age_s=max_age_s)
    if cached is not None:
        return cached

    src = source_name(url)
    if _is_offline():
        raise SourceUnavailable(src, "offline and not cached")

    with _url_lock(full):
        # Re-check inside the per-URL lock in case another waiter just populated the cache.
        cached, stale = _read_if_fresh(path, refresh=refresh, max_age_s=max_age_s)
        if cached is not None:
            return cached
        _record_network_fetch()
        try:
            return _fetch_and_store(full, path, src, headers, validate, timeout)
        except SourceUnavailable:
            if stale:
                return path.read_text(encoding="utf-8")
            raise


def _fetch_and_store(
    full: str,
    path: Path,
    src: str,
    headers: dict | None,
    validate: Callable[[str], Any] | None,
    timeout: float,
) -> str:

    last_err = "unknown error"
    req_headers = {**_UA, **(headers or {})}

    for attempt in range(_RETRIES):
        try:
            req = urllib.request.Request(full, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8")
            if validate is not None:
                if validate(text) is False:
                    raise ValueError("response failed validation")
            cdir = path.parent
            cdir.mkdir(parents=True, exist_ok=True)
            tmp = cdir / f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            return text
        except urllib.error.HTTPError as exc:
            # Client errors other than 429 are not transient; fail fast.
            if 400 <= exc.code < 500 and exc.code != 429:
                raise SourceUnavailable(src, f"HTTP {exc.code}: {exc.reason}") from exc
            last_err = f"HTTP {exc.code}: {exc.reason}"
        except Exception as exc:
            last_err = str(exc) or type(exc).__name__

        if attempt < _RETRIES - 1:
            time.sleep(2 * (attempt + 1))

    raise SourceUnavailable(src, f"request failed after {_RETRIES} attempts: {last_err}")


def get_json(
    url: str,
    params: dict | None = None,
    *,
    headers: dict | None = None,
    refresh: bool = False,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> Any:
    """Fetch and parse a JSON response with file caching and retries."""
    text = get_text(
        url,
        params,
        headers=headers,
        ext="json",
        refresh=refresh,
        validate=json.loads,
        timeout=timeout,
    )
    return json.loads(text)
