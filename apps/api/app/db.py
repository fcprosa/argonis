"""
Supabase client helpers.

Provides a lazily-initialised service-role client that bypasses RLS.
All endpoint handlers use it for DB operations and enforce authorization
by filtering on ``organization_id`` from the verified JWT.

NOTE (v1 limitation): Because we use the service-role key, the DB
audit-log triggers record ``user_id`` as NULL (``auth.uid()`` is not
set).  The full change history (table, record_id, old_data, new_data)
is still captured.  Proper user attribution can be added later via
per-request clients with the user JWT or PostgreSQL session variables.
"""

from __future__ import annotations

from supabase import AsyncClient, acreate_client

from app.config import settings

_service_client: AsyncClient | None = None


async def get_service_db() -> AsyncClient:
    """Return a Supabase client with the **service role key** (bypasses RLS).

    The client is created once and reused across requests.

    Raises ``RuntimeError`` if Supabase credentials are not configured.
    """
    global _service_client  # noqa: PLW0603
    if _service_client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError(
                "Supabase not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY."
            )
        _service_client = await acreate_client(
            settings.supabase_url,
            settings.supabase_service_key,
        )
    return _service_client
