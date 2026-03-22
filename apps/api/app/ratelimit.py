"""
In-memory sliding-window rate limiter.

ANTI-ERROR: Rate limiting from day 1.
An errant loop calling /investigate burns $500 in Claude credits in minutes.

Default limits (per user per minute):
  /investigate:     5  (Claude API calls = expensive)
  /alerts/batch:   10  (batch operations)
  General:         60  (read endpoints)

Uses a simple sliding window with in-memory storage.
For multi-instance deployments, migrate to Redis.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

import jwt as pyjwt
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sliding window internals
# ---------------------------------------------------------------------------


@dataclass
class _SlidingWindow:
    """Timestamps of recent requests within a window."""

    timestamps: list[float] = field(default_factory=list)

    def clean(self, window_seconds: float) -> None:
        cutoff = time.monotonic() - window_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]

    def count(self) -> int:
        return len(self.timestamps)

    def add(self) -> None:
        self.timestamps.append(time.monotonic())


class RateLimiter:
    """
    In-memory sliding window rate limiter.

    Thread-safe for single-threaded async event loop (FastAPI/uvicorn).
    NOT safe for multi-process deployments — use Redis for that.
    """

    def __init__(self) -> None:
        self._windows: dict[str, _SlidingWindow] = defaultdict(_SlidingWindow)
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 300.0  # purge stale entries every 5 min

    def _maybe_cleanup(self) -> None:
        """Periodically purge stale entries to prevent memory leaks."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale = [
            k
            for k, w in self._windows.items()
            if not w.timestamps or w.timestamps[-1] < now - 3600
        ]
        for k in stale:
            del self._windows[k]

    def check(
        self, key: str, max_requests: int, window_seconds: float
    ) -> tuple[bool, dict[str, str]]:
        """
        Check whether the request is allowed.

        Returns ``(allowed, headers)`` where *headers* contains standard
        ``X-RateLimit-*`` fields suitable for the HTTP response.
        """
        self._maybe_cleanup()

        window = self._windows[key]
        window.clean(window_seconds)

        remaining = max(0, max_requests - window.count())
        headers = {
            "X-RateLimit-Limit": str(max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Window": f"{int(window_seconds)}s",
        }

        if window.count() >= max_requests:
            oldest = min(window.timestamps) if window.timestamps else time.monotonic()
            retry_after = int(oldest + window_seconds - time.monotonic()) + 1
            headers["Retry-After"] = str(max(1, retry_after))
            return False, headers

        window.add()
        remaining = max(0, max_requests - window.count())
        headers["X-RateLimit-Remaining"] = str(remaining)
        return True, headers


# Singleton — shared by all endpoints
_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


def rate_limit(max_requests: int = 60, window_seconds: float = 60.0):
    """
    FastAPI dependency factory for rate limiting.

    Usage::

        @router.post("/investigate")
        async def investigate(
            _rl: None = Depends(rate_limit(5, 60)),   # 5 req/min
            auth: AuthContext = Depends(get_current_user),
        ):
            ...

    The rate-limit key is ``{user_id}:{request_path}``.
    If no JWT is present the key falls back to the client IP.
    """

    async def _check_rate_limit(request: Request) -> None:
        # Cheap user-id extraction (signature already verified by auth dep)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                payload = pyjwt.decode(
                    auth_header[7:],
                    options={"verify_signature": False},
                )
                user_id = payload.get("sub", "anonymous")
            except Exception:
                user_id = "anonymous"
        else:
            user_id = request.client.host if request.client else "unknown"

        key = f"{user_id}:{request.url.path}"
        allowed, headers = _limiter.check(key, max_requests, window_seconds)

        if not allowed:
            logger.warning(
                "Rate limit exceeded: user=%s path=%s limit=%d/%ds",
                user_id,
                request.url.path,
                max_requests,
                int(window_seconds),
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit exceeded. Max {max_requests} requests per "
                    f"{int(window_seconds)}s. Retry after "
                    f"{headers.get('Retry-After', '?')}s."
                ),
                headers=headers,  # type: ignore[arg-type]
            )

        # Stash headers so the middleware can copy them to the response
        request.state.rate_limit_headers = headers

    return _check_rate_limit
