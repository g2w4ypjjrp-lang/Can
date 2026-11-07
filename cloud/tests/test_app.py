from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from ati_cloud.app import create_app
from ati_cloud.config import CloudSettings


async def _get(app: object, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_health() -> None:
    app = create_app(CloudSettings(database_url=SecretStr("postgresql://x@127.0.0.1:1/x")))
    response = await _get(app, "/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_ready_when_database_unreachable() -> None:
    app = create_app(CloudSettings(database_url=SecretStr("postgresql://x@127.0.0.1:1/x")))
    response = await _get(app, "/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


async def test_ready_with_migrated_database(dsn: str) -> None:
    app = create_app(CloudSettings(database_url=SecretStr(dsn)))
    response = await _get(app, "/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready"}


async def test_ready_reports_pending_migrations(empty_dsn: str) -> None:
    app = create_app(CloudSettings(database_url=SecretStr(empty_dsn)))
    response = await _get(app, "/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "migrations_pending"


def test_production_requires_verified_tls() -> None:
    with pytest.raises(ValidationError, match="TLS"):
        CloudSettings(environment="production", database_url=SecretStr("postgresql://u@db/x"))
    with pytest.raises(ValidationError, match="TLS"):
        CloudSettings(
            environment="production", database_url=SecretStr("postgresql://u@db/x?sslmode=require")
        )
    CloudSettings(
        environment="production", database_url=SecretStr("postgresql://u@db/x?sslmode=verify-full")
    )
