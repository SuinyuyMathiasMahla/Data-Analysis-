"""Small in-process sliding-window rate limiter.

Good enough for a single API process. Behind several workers or servers,
replace the ``_hits`` store with Redis (same interface) - see docs/architecture.md.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import ApiError

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_rate(key: str, limit: int, window_seconds: int = 60) -> None:
    now = time.monotonic()
    with _lock:
        bucket = _hits[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            retry = max(1, int(window_seconds - (now - bucket[0])))
            raise ApiError(429, "rate_limited", f"Too many requests. Try again in {retry} seconds.")
        bucket.append(now)


def reset_rate_limits() -> None:
    with _lock:
        _hits.clear()
