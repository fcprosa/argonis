"""
Supabase JWT authentication for FastAPI.

All endpoints (except /health) require a valid Supabase JWT in the
Authorization header. The JWT is verified locally using SUPABASE_JWT_SECRET.

Demo mode (DEMO_MODE=true): GET requests with header ``X-Demo-Mode: true`` use a
synthetic AuthContext (no JWT). Non-GET always requires JWT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# AuthContext — injected into every protected endpoint
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Authenticated user context, available as a FastAPI dependency."""

    user_id: str
    organization_id: str
    role: str  # 'admin' | 'analyst' | 'reviewer'
    email: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_record(user_id: str) -> dict:
    """Fetch user record from Supabase using service key (bypasses RLS)."""
    from supabase import acreate_client

    client = await acreate_client(settings.supabase_url, settings.supabase_service_key)
    result = (
        await client.table("users")
        .select("organization_id, role, email")
        .eq("id", user_id)
        .single()
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# Main dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthContext:
    """
    FastAPI dependency — verify Supabase JWT and return AuthContext.

    Demo bypass: ``DEMO_MODE`` + ``GET`` + ``X-Demo-Mode: true`` → synthetic
    analyst context for ``DEMO_ORG_ID`` / ``DEMO_USER_ID``.
    """
    if (
        settings.demo_mode
        and request.method == "GET"
        and request.headers.get("x-demo-mode", "").lower() == "true"
    ):
        return AuthContext(
            user_id=settings.demo_user_id.strip(),
            organization_id=settings.demo_org_id.strip(),
            role="analyst",
            email="demo@argonis.local",
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = credentials.credentials

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not configured (SUPABASE_JWT_SECRET required)",
        )

    try:
        payload = pyjwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim",
        )

    try:
        user_record = await _get_user_record(user_id)
    except Exception as exc:
        logger.error("Failed to fetch user record for %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found in organization",
        )

    return AuthContext(
        user_id=user_id,
        organization_id=user_record["organization_id"],
        role=user_record["role"],
        email=user_record.get("email", payload.get("email", "")),
    )


# ---------------------------------------------------------------------------
# Role-gating dependency factory
# ---------------------------------------------------------------------------


def require_role(*roles: str):
    """
    FastAPI dependency factory — require specific roles.

    Usage::

        @router.post("/admin-only")
        async def admin_only(
            auth: AuthContext = Depends(require_role("admin")),
        ):
            ...
    """

    async def _check_role(
        auth: AuthContext = Depends(get_current_user),
    ) -> AuthContext:
        if auth.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {', '.join(roles)}",
            )
        return auth

    return _check_role
