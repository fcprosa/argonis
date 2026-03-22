from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import alerts, audit, cases, health, investigations, narratives, screening

app = FastAPI(
    title="Argonis API",
    version="0.0.1",
    description="Evidence-first AML investigation platform",
)

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
