from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.environment,
        "version": "0.0.1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
