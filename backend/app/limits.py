"""In-process concurrency guards and per-client sliding-window rate limiting."""
from __future__ import annotations

from collections import OrderedDict, deque
from contextlib import asynccontextmanager
import ipaddress
import math
import os
import threading
import time

from fastapi import Request

BUSY_MESSAGE = "The live service is busy. Try again in a minute or open a saved case."

RATE_LIMITS: dict[str, tuple[int, float]] = {
    "check": (10, 60.0),
    "event": (4, 60.0),
    "chat": (5, 60.0),
    "parse": (10, 60.0),
}


class BusyError(Exception):
    """Raised when an endpoint group's concurrency slots are all in use."""

    def __init__(self, message: str = BUSY_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


class RateLimitError(Exception):
    """Raised when a client exceeds a route group's per-client rate limit."""

    def __init__(self, retry_after: int, message: str | None = None) -> None:
        self.retry_after = max(1, int(retry_after))
        self.message = message or f"Too many requests. Try again in {self.retry_after} s."
        super().__init__(self.message)


class ConcurrencyGate:
    """Non-blocking concurrency slot counter safe across event loops and threads."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._active = 0
        self._lock = threading.Lock()

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def try_acquire(self) -> bool:
        with self._lock:
            if self._active >= self.limit:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._active > 0:
                self._active -= 1

    @asynccontextmanager
    async def slot(self):
        if not self.try_acquire():
            raise BusyError()
        try:
            yield
        finally:
            self.release()


def concurrency_guard(gate: ConcurrencyGate):
    """FastAPI dependency that acquires a slot non-blockingly and always releases it."""

    async def _guard():
        async with gate.slot():
            yield

    return _guard


def _is_loopback(host: str) -> bool:
    if host in ("127.0.0.1", "::1"):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or (addr.ipv4_mapped is not None and addr.ipv4_mapped.is_loopback)


def _forwarded_ip(request: Request) -> str:
    """Extract client IP from Cloudflare or Tailscale Funnel forwarding headers."""
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    xff_raw = ",".join(request.headers.getlist("x-forwarded-for"))
    parts = [p.strip() for p in xff_raw.split(",") if p.strip()]
    return parts[-1] if parts else ""


def client_ip(request: Request) -> str:
    """Resolve client IP, trusting proxy headers only from a loopback peer."""
    peer = request.client.host if request.client and request.client.host else ""
    if _is_loopback(peer):
        forwarded = _forwarded_ip(request)
        if forwarded:
            return forwarded
    return peer


def _is_exempt_local(request: Request) -> bool:
    """Exempt unproxied loopback callers (e.g. local warm-up) when opted in."""
    flag = os.environ.get("EV_RATE_LIMIT_EXEMPT_LOCAL", "").strip().lower() in ("1", "true", "yes")
    if not flag:
        return False
    peer = request.client.host if request.client and request.client.host else ""
    return _is_loopback(peer) and not _forwarded_ip(request)


class RateLimiter:
    """Thread-safe sliding-window rate limiter with bounded LRU/expiry pruning."""

    def __init__(self, max_keys: int = 4096) -> None:
        self.max_keys = max(1, max_keys)
        self._buckets: OrderedDict[tuple[str, str], tuple[deque[float], float]] = OrderedDict()
        self._lock = threading.Lock()
        self._ops = 0

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._ops = 0

    def _prune_locked(self, now: float) -> None:
        while self._buckets:
            _, (dq, window) = next(iter(self._buckets.items()))
            while dq and now - dq[0] >= window:
                dq.popleft()
            if not dq:
                self._buckets.popitem(last=False)
            else:
                break
        if self._ops % 256 == 0:
            dead = [k for k, (dq, w) in self._buckets.items() if not dq or now - dq[-1] >= w]
            for k in dead:
                del self._buckets[k]
        while self._buckets and len(self._buckets) >= self.max_keys:
            self._buckets.popitem(last=False)

    def allow(
        self,
        group: str,
        client_key: str,
        limit: int,
        window: float,
        *,
        now: float | None = None,
    ) -> tuple[bool, int]:
        if limit <= 0:
            return False, max(1, math.ceil(window))
        t = time.monotonic() if now is None else now
        full_key = (group, client_key)
        with self._lock:
            self._ops += 1
            entry = self._buckets.get(full_key)
            if entry is not None:
                dq, _ = entry
                while dq and t - dq[0] >= window:
                    dq.popleft()
                if not dq:
                    del self._buckets[full_key]
                    entry = None
            if entry is None:
                self._prune_locked(t)
                self._buckets[full_key] = (deque([t]), window)
                return True, 0
            dq, _ = entry
            self._buckets.move_to_end(full_key)
            if len(dq) >= limit:
                retry_after = max(1, math.ceil(window - (t - dq[0])))
                return False, retry_after
            dq.append(t)
            self._buckets[full_key] = (dq, window)
            return True, 0


check_gate = ConcurrencyGate(4)
event_gate = ConcurrencyGate(2)
rate_limiter = RateLimiter()


def rate_guard(group: str):
    """FastAPI dependency enforcing the per-client sliding-window rate limit."""

    async def _guard(request: Request) -> None:
        if _is_exempt_local(request):
            return
        limit, window = RATE_LIMITS[group]
        allowed, retry_after = rate_limiter.allow(group, client_ip(request), limit, window)
        if not allowed:
            raise RateLimitError(retry_after)

    return _guard
