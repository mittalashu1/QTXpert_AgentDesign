"""Lightweight rate limiting middleware.

Uses an in-process sliding window by default so the app runs standalone in
local/dev without Redis. In production (multiple Render instances), swap
`_InMemoryLimiter` for a Redis-backed limiter using the same `RateLimiter`
interface - no route code changes needed.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings


class _InMemoryLimiter:
    def __init__(self, limit_per_minute: int):
        self._limit = limit_per_minute
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - 60
        hits = self._hits[key]
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self._limiter = _InMemoryLimiter(settings.RATE_LIMIT_PER_MINUTE)

    async def dispatch(self, request: Request, call_next) -> Response:
        client_key = request.client.host if request.client else "unknown"
        if request.url.path == "/api/v1/health":
            return await call_next(request)
        if not self._limiter.allow(client_key):
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
            )
        return await call_next(request)
