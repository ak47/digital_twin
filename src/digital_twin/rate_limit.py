"""Simple in-memory per-IP rate limit (app-level; resets on instance recycle)."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Callable

_rpm_limit = max(1, int(os.environ.get("RATE_LIMIT_REQUESTS_PER_MINUTE", "30")))
_window = 60.0

_timestamps: dict[str, list[float]] = defaultdict(list)


def client_ip(get_header: Callable[[str], str | None], fallback: str | None) -> str:
    xff = (get_header("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return fallback or "unknown"


def check_rate_limit(ip: str) -> None:
    limit = _rpm_limit
    now = time.monotonic()
    window_start = now - _window
    hits = _timestamps[ip]
    while hits and hits[0] < window_start:
        hits.pop(0)
    if len(hits) >= limit:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=429,
            detail="Too many requests; try again shortly.",
            headers={"Retry-After": "60"},
        )
    hits.append(now)
