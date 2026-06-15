"""Fast rejection of requests outside the known API surface.

Scanners commonly probe for PHP panels, WordPress paths, and similar URLs. Those
requests never match real routes but still traverse the full middleware stack.
Reject them early with a plain 404 so they cannot trigger deeper handlers.
"""

from __future__ import annotations

_ALLOWED_EXACT = frozenset(
    {
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)

_ALLOWED_PREFIXES = (
    "/api/",
    "/admin/",
    "/family/",
)


def is_allowed_path(path: str) -> bool:
    """Return True when *path* belongs to this service's public API surface."""
    if path in _ALLOWED_EXACT:
        return True
    if path.startswith(("/health/", "/docs/")):
        return True
    return any(path.startswith(prefix) for prefix in _ALLOWED_PREFIXES)
