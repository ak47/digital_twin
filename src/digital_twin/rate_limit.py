"""Simple in-memory per-IP rate limit (app-level; resets on instance recycle)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

_window = 60.0

from digital_twin.settings import get_settings

_timestamps: dict[str, deque[float]] = defaultdict(deque)


def client_ip(get_header: Callable[[str], str | None], fallback: str | None) -> str:
    xff = (get_header("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return fallback or "unknown"


def check_rate_limit(ip: str) -> None:
    limit = get_settings().rate_limit_requests_per_minute
    now = time.monotonic()
    window_start = now - _window
    hits = _timestamps[ip]
    while hits and hits[0] < window_start:
        hits.popleft()
    if len(hits) >= limit:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=429,
            detail="Too many requests; try again shortly.",
            headers={"Retry-After": "60"},
        )
    hits.append(now)
