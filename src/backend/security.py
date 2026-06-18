"""
Security and request limiting helpers for the backend.
"""

from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic

from fastapi import Request


class RequestRateLimiter:
    """Simple in-memory fixed-window rate limiter."""

    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        if limit <= 0 or window_seconds <= 0:
            return True

        now = monotonic()
        bucket = self._buckets[key]
        cutoff = now - window_seconds

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            return False

        bucket.append(now)
        return True


def extract_client_ip(request: Request) -> str:
    """Return the best-effort client IP for request logging and rate limiting."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def parse_bearer_token(request: Request) -> str | None:
    """Extract a bearer token or x-api-key value."""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    x_api_key = request.headers.get("x-api-key")
    if x_api_key:
        return x_api_key.strip()
    return None
