from __future__ import annotations

import base64
from pathlib import Path

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


LICENSE_SECRETS = {
    "license_pepper": SecretStr(base64.b64encode(b"p" * 32).decode()),
    "license_kek": SecretStr(base64.b64encode(b"k" * 32).decode()),
    "lease_signing_key": SecretStr(base64.b64encode(b"s" * 32).decode()),
}
SITE = {
    "public_web_url": "https://canarslan.net.tr",
    "web_origins": ["https://canarslan.net.tr"],
    **LICENSE_SECRETS,
}


def test_production_requires_verified_tls() -> None:
    with pytest.raises(ValidationError, match="TLS"):
        CloudSettings(
            environment="production", database_url=SecretStr("postgresql://u@db/x"), **SITE
        )
    with pytest.raises(ValidationError, match="TLS"):
        CloudSettings(
            environment="production",
            database_url=SecretStr("postgresql://u@db/x?sslmode=require"),
            **SITE,
        )
    CloudSettings(
        environment="production",
        database_url=SecretStr("postgresql://u@db/x?sslmode=verify-full"),
        **SITE,
    )


def test_production_requires_license_secrets() -> None:
    dsn = SecretStr("postgresql://u@db/x?sslmode=verify-full")
    site = {k: v for k, v in SITE.items() if k != "lease_signing_key"}
    with pytest.raises(ValidationError, match="ATI_LEASE_SIGNING_KEY"):
        CloudSettings(environment="production", database_url=dsn, **site)


def test_production_requires_https_site_and_origins() -> None:
    dsn = SecretStr("postgresql://u@db/x?sslmode=verify-full")
    with pytest.raises(ValidationError, match="HTTPS"):
        CloudSettings(environment="production", database_url=dsn)  # varsayılan: localhost http
    with pytest.raises(ValidationError, match="http://canarslan"):
        CloudSettings(
            environment="staging",
            database_url=dsn,
            public_web_url="https://canarslan.net.tr",
            web_origins=["https://canarslan.net.tr", "http://canarslan.net.tr"],
            **LICENSE_SECRETS,
        )


def test_production_example_settings_are_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """deploy/cloud.env.example üretimde geçerli bir yapılandırmadır."""
    example = Path(__file__).resolve().parents[2] / "deploy" / "cloud.env.example"
    for line in example.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("ATI_DATABASE_URL", "postgresql://u@db/x?sslmode=verify-full")
    for name, value in LICENSE_SECRETS.items():  # gizli bilgi deposundan gelir
        monkeypatch.setenv(f"ATI_{name.upper()}", value.get_secret_value())
    cfg = CloudSettings()
    assert cfg.environment == "production"
    assert cfg.web_origins == ["https://canarslan.net.tr"]
    assert cfg.trusted_proxies == ["10.0.0.0/8"]
    assert cfg.session_cookie_secure is True
