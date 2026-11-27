import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import approvals, dashboard, health, operations, organizations, tasks
from .auth import TokenVerifier
from .config import Settings, get_settings
from .db import Database
from .dispatch import CeleryDispatcher, Dispatcher, InlineDispatcher, make_orchestrator
from .middleware import RateLimitMiddleware, RequestContextMiddleware, setup_logging
from .scheduler import tick


def create_app(settings: Settings | None = None, db: Database | None = None,
               dispatcher: Dispatcher | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = db or Database(settings.database_url, settings.db_pool_max)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await database.open()
        loop_task = None
        if settings.inline_scheduler and not settings.redis_url:
            loop_task = asyncio.create_task(_scheduler_loop(app))
        yield
        if loop_task:
            loop_task.cancel()
        if isinstance(app.state.dispatcher, InlineDispatcher):
            await app.state.dispatcher.drain()
        await database.close()

    docs = None if settings.environment == "production" else "/docs"
    app = FastAPI(title="AI Business Center API", version="0.1.0", lifespan=lifespan,
                  docs_url=docs, redoc_url=None, openapi_url=docs and "/openapi.json")
    app.state.db = database
    app.state.verifier = TokenVerifier(settings)
    app.state.settings = settings
    app.state.dispatcher = dispatcher or (
        CeleryDispatcher() if settings.redis_url else InlineDispatcher(make_orchestrator(settings, database)))
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_minute)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["authorization", "content-type", "x-request-id"])
    app.add_middleware(RequestContextMiddleware)
    for r in (health.router, organizations.router, dashboard.router, approvals.router, tasks.router,
              operations.router):
        app.include_router(r)
    return app


async def _scheduler_loop(app: FastAPI) -> None:
    while True:
        try:
            await tick(app.state.db, app.state.dispatcher, app.state.settings.max_active_tasks_per_org)
        except Exception:
            logging.getLogger("bizcenter.scheduler").exception("scheduler tick failed")
        await asyncio.sleep(60)


def run() -> None:
    import uvicorn

    setup_logging()
    uvicorn.run("bizcenter.main:create_app", factory=True, host="0.0.0.0", port=8000,  # noqa: S104
                proxy_headers=True, log_config=None)
