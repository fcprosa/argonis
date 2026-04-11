import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.routers import admin, alerts, audit, cases, health, investigations, kyc, narratives, screening

logger = logging.getLogger("argonis.startup")


async def _check_ofac_health() -> None:
    """Log loud warnings if OFAC SDN data is empty or stale."""
    if not settings.supabase_url or not settings.supabase_service_key:
        return

    try:
        from app.db import get_service_db

        db = await get_service_db()

        count_result = await (
            db.table("ofac_sdn_entries")
            .select("id", count="exact")
            .limit(0)
            .execute()
        )
        entry_count = count_result.count or 0

        if entry_count == 0:
            logger.critical(
                "⚠ CRITICAL: OFAC SDN tables are empty. "
                "POST /screening/ofac/refresh before running any investigations."
            )
            return

        refresh_result = await (
            db.table("ofac_refresh_log")
            .select("refreshed_at")
            .order("refreshed_at", desc=True)
            .limit(1)
            .execute()
        )
        if refresh_result.data:
            refreshed_at = refresh_result.data[0]["refreshed_at"]
            dt = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
            hours_ago = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
            if hours_ago > 168:
                logger.warning(
                    "OFAC SDN data is stale (last refreshed %.1f hours ago). "
                    "Consider refreshing.",
                    hours_ago,
                )
            else:
                logger.info(
                    "OFAC SDN: %d entries, last refreshed %.1f hours ago — OK",
                    entry_count,
                    hours_ago,
                )
        else:
            logger.warning(
                "OFAC SDN: %d entries loaded but no refresh log found. "
                "Staleness cannot be determined.",
                entry_count,
            )
    except Exception as exc:
        logger.warning("OFAC health check failed (non-blocking): %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await _check_ofac_health()
    yield


app = FastAPI(
    title="Argonis API",
    version="0.0.1",
    description="Evidence-first AML investigation platform",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware: copy rate-limit headers onto every response
# ---------------------------------------------------------------------------


@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next) -> Response:  # type: ignore[type-arg]
    response: Response = await call_next(request)
    if hasattr(request.state, "rate_limit_headers"):
        for key, value in request.state.rate_limit_headers.items():
            response.headers[key] = value
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health.router)
app.include_router(screening.router)
app.include_router(alerts.router)
app.include_router(investigations.router)
app.include_router(cases.router)
app.include_router(narratives.router)
app.include_router(audit.router)
app.include_router(admin.router)
app.include_router(kyc.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
