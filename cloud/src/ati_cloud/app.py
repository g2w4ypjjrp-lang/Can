"""Bulut servisi uygulama iskeleti.

Sağlık uç noktaları (Aşama 1), müşteri hesapları ve iletişim formu (Aşama 14). Lisans,
ödeme ve yönetici API'leri sırasıyla Aşama 15-17'de eklenecektir. Yönetici API'si ayrı bir
yönlendirici (``/admin``), ayrı oturum tablosu ve zorunlu 2FA ile çalışacaktır.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ati_cloud import __version__
from ati_cloud.accounts import Database, create_accounts_router
from ati_cloud.config import CloudSettings
from ati_cloud.contact import create_contact_router
from ati_cloud.db.migrate import load_migrations, pending
from ati_cloud.licensing.api import create_license_router
from ati_cloud.licensing.service import Licensing


def _check_database(dsn: str) -> list[int]:
    """Veritabanına bağlanır ve bekleyen geçişlerin sürümlerini döner (salt okuma)."""
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as conn:
        conn.execute("SELECT 1")
        return [m.version for m in pending(conn, load_migrations())]


def get_settings(request: Request) -> CloudSettings:
    settings: CloudSettings = request.app.state.settings
    return settings


Settings = Annotated[CloudSettings, Depends(get_settings)]


def create_app(settings: CloudSettings | None = None) -> FastAPI:
    cfg = settings or CloudSettings()
    db = Database(cfg.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await db.close()

    app = FastAPI(
        title="AI Trading Intelligence Cloud",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.db = db
    # Web sitesi müşteri paneli: yalnızca kendi kökenimizden, çerezle (SameSite=Strict).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.web_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(create_accounts_router(cfg, db))
    app.include_router(create_contact_router(cfg, db))
    app.state.licensing = Licensing.from_settings(cfg)
    app.include_router(create_license_router(cfg, db, app.state.licensing))

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Canlılık: süreç ayakta mı?"""
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    async def ready(cfg: Settings) -> JSONResponse:
        """Hazırlık: veritabanı erişilebilir ve şema güncel mi?"""
        try:
            outstanding = await asyncio.to_thread(
                _check_database, cfg.database_url.get_secret_value()
            )
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "reason": type(exc).__name__},
            )
        if outstanding:
            return JSONResponse(
                status_code=503,
                content={"status": "migrations_pending", "pending": outstanding},
            )
        return JSONResponse(content={"status": "ready"})

    return app
