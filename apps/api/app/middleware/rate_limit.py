"""
Rate limiting for the /investigate endpoint.

Battle plan rationale:
  "An errant loop calling /investigate burns $500 in Claude credits in minutes."

Each investigation triggers a full Claude API call (~$0.30-1.00). Three tiers
of limits protect against runaway costs:

  PER-USER limits catch a single analyst or script hitting the endpoint in a
  tight loop. 10/min and 100/hour are generous for human workflows but stop
  automation disasters.

  PER-ORG limits catch the case where multiple users in the same org hit the
  endpoint simultaneously (e.g. a batch script running under several service
  accounts). 500/day caps the org at roughly $150-500/day worst case.

Storage: in-memory by default. Set REDIS_URL for multi-instance deployments
where each uvicorn worker needs a shared counter.
"""

from __future__ import annotations

import logging

import jwt as pyjwt
from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limit constants
# ---------------------------------------------------------------------------

INVESTIGATE_USER_MINUTE = "10/minute"
INVESTIGATE_USER_HOUR = "100/hour"
INVESTIGATE_ORG_DAY = "500/day"


# ---------------------------------------------------------------------------
# Key functions — extract user_id / org_id from the JWT
# ---------------------------------------------------------------------------


def _get_user_id_from_request(request: Request) -> str:
    """Extract user_id from Bearer token without full verification.

    The auth dependency verifies the signature separately; here we only
    need a stable key for the rate limiter.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = pyjwt.decode(
                auth_header[7:], options={"verify_signature": False}
            )
            return payload.get("sub", get_remote_address(request))
        except Exception:
            pass
    return get_remote_address(request)


def get_user_key(request: Request) -> str:
    """Rate limit key: user_id (or IP fallback)."""
    return _get_user_id_from_request(request)


def get_org_key(request: Request) -> str:
    """Rate limit key: organization_id extracted from the JWT.

    Falls back to the user key when the org claim isn't present (the full
    org lookup happens in the auth dependency, but Supabase JWTs carry
    user_metadata that may include it). If unavailable, we key on user_id
    which is still a reasonable fallback — the per-user limits will fire
    first anyway.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = pyjwt.decode(
                auth_header[7:], options={"verify_signature": False}
            )
            # Supabase stores org in app_metadata or user_metadata depending
            # on setup; fall back to sub if neither is set.
            meta = payload.get("app_metadata") or {}
            org_id = meta.get("organization_id")
            if org_id:
                return f"org:{org_id}"
            return payload.get("sub", get_remote_address(request))
        except Exception:
            pass
    return get_remote_address(request)


# ---------------------------------------------------------------------------
# Limiter instance
# ---------------------------------------------------------------------------

_storage_uri = settings.redis_url if settings.redis_url else "memory://"

limiter = Limiter(
    key_func=get_user_key,
    storage_uri=_storage_uri,
    strategy="fixed-window",
)


# ---------------------------------------------------------------------------
# Custom 429 handler
# ---------------------------------------------------------------------------


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a structured JSON body on 429 instead of plain text."""
    retry_after = int(exc.detail.split("retry after ")[1].split(" ")[0]) if "retry after" in exc.detail.lower() else 60

    limit_str = str(getattr(exc, "limit", exc.detail))

    logger.warning(
        "rate_limit_exceeded: path=%s key=%s limit=%s",
        request.url.path,
        get_user_key(request),
        limit_str,
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "limit": limit_str,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
