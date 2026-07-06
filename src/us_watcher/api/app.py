"""FastAPI application factory.

Wires logging, CORS, security headers, and the public/protected routers under
``/api/v1``. On startup (SQLite/dev) it ensures the schema exists and seeds the
instrument universe; in prod the schema is owned by Alembic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from us_watcher.config import get_settings
from us_watcher.logging_config import configure_logging, get_logger

log = get_logger(__name__)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    if settings.is_sqlite:
        # Dev convenience: ensure schema + seed. Prod uses Alembic migrations.
        from us_watcher.db.seed import seed_instruments
        from us_watcher.infrastructure.db import create_all

        await create_all()
        await seed_instruments()
        log.info("startup.schema_ready", backend="sqlite")
    # Warm the market-overview snapshot in the background so the first page load
    # doesn't pay the cold live-fetch cost. Best-effort; never blocks startup.
    import asyncio

    from us_watcher.market.service import get_market_service

    prewarm = asyncio.create_task(get_market_service().prewarm())
    try:
        yield
    finally:
        prewarm.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="US Stock Watcher API",
        version=settings.app_version,
        description="United States equity market intelligence API.",
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Never drop the connection on an unhandled error — return a clean, labelled
        # 500 so the frontend treats it as a deterministic failure (not a phantom
        # "API connection failed") and the server keeps serving other requests.
        log.error("api.unhandled_exception", path=request.url.path, error=str(exc)[:300], exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "status": "error"})

    from us_watcher.api.routes import (
        accuracy,
        agents,
        briefings,
        health,
        indices,
        macro,
        market,
        news,
        recommendations,
        refresh,
        sectors,
    )

    app.include_router(health.router)
    api = "/api/v1"
    app.include_router(market.router, prefix=api)
    app.include_router(indices.router, prefix=api)
    app.include_router(sectors.router, prefix=api)
    app.include_router(macro.router, prefix=api)
    app.include_router(recommendations.router, prefix=api)
    app.include_router(news.router, prefix=api)
    app.include_router(briefings.router, prefix=api)
    app.include_router(agents.router, prefix=api)
    app.include_router(accuracy.router, prefix=api)
    app.include_router(refresh.router, prefix=api)
    return app
