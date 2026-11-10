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
    "admin_secret_kek": SecretStr(base64.b64encode(b"a" * 32).decode()),
}
SITE = {
    "public_web_url": "https://canarslan.net.tr",
    "web_origins": ["https://canarslan.net.tr"],
    "admin_public_url": "https://admin.canarslan.net.tr",
    "admin_origins": ["https://admin.canarslan.net.tr"],
    "public_api_url": "https://api.canarslan.net.tr",
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


def test_private_network_tls_must_be_chosen_explicitly() -> None:
    """Yönetilen platformun özel ağı (kendinden imzalı sertifika): ``require`` yalnızca açık ayarla."""
    internal = SecretStr("postgresql://ati:gizli@dpg-abc-a/ati")
    with pytest.raises(ValidationError, match="TLS"):
        CloudSettings(environment="production", database_url=internal, **SITE)
    settings = CloudSettings(
        environment="production", database_url=internal, database_sslmode="require", **SITE
    )
    assert "sslmode=require" in settings.database_dsn
    assert "host=dpg-abc-a" in settings.database_dsn and "password=gizli" in settings.database_dsn
    # Geçersiz kip kabul edilmez; ayar adresteki zayıf kipi de geçersiz kılar.
    with pytest.raises(ValidationError):
        CloudSettings(
            environment="production", database_url=internal, database_sslmode="disable", **SITE
        )
    weak = SecretStr("postgresql://u@db/x?sslmode=disable")
    strict = CloudSettings(
        environment="production", database_url=weak, database_sslmode="verify-full", **SITE
    )
    assert "sslmode=verify-full" in strict.database_dsn and "disable" not in strict.database_dsn


@pytest.mark.parametrize(
    ("dsn", "allowed"),
    [
        ("postgresql://ati:x@127.0.0.1:5432/ati", True),
        ("postgresql://ati:x@localhost/ati", True),
        ("postgresql://ati:x@[::1]/ati", True),
        ("host=/var/run/postgresql dbname=ati", True),
        ("postgresql://ati:x@127.0.0.1,10.0.0.5/ati", False),  # biri uzak
        ("postgresql://ati:x@10.0.0.5/ati", False),
        ("postgresql://ati:x@db.example/ati", False),
        ("host=localhost hostaddr=10.0.0.5 dbname=ati", False),  # gerçek adres uzak
    ],
)
def test_same_machine_database_needs_no_tls(dsn: str, allowed: bool) -> None:
    """Kendi sunucunuzda (Windows VDS) veritabanı aynı makinede: trafik ağa çıkmaz."""
    if allowed:
        CloudSettings(environment="production", database_url=SecretStr(dsn), **SITE)
    else:
        with pytest.raises(ValidationError, match="TLS"):
            CloudSettings(environment="production", database_url=SecretStr(dsn), **SITE)


def test_production_requires_admin_kek_and_https_admin() -> None:
    dsn = SecretStr("postgresql://u@db/x?sslmode=verify-full")
    without_kek = {k: v for k, v in SITE.items() if k != "admin_secret_kek"}
    with pytest.raises(ValidationError, match="ATI_ADMIN_SECRET_KEK"):
        CloudSettings(environment="production", database_url=dsn, **without_kek)
    with pytest.raises(ValidationError, match="yönetici ve API adresleri"):
        CloudSettings(
            environment="production",
            database_url=dsn,
            **{**SITE, "admin_origins": ["http://admin.canarslan.net.tr"]},
        )
    # Ödeme sağlayıcısı tarayıcıyı ve bildirimleri API adresine gönderir: HTTPS zorunlu.
    with pytest.raises(ValidationError, match=r"http://api\.canarslan"):
        CloudSettings(
            environment="production",
            database_url=dsn,
            **{**SITE, "public_api_url": "http://api.canarslan.net.tr"},
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
            admin_public_url="https://admin.canarslan.net.tr",
            admin_origins=["https://admin.canarslan.net.tr"],
            public_api_url="https://api.canarslan.net.tr",
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
    assert cfg.admin_origins == ["https://admin.canarslan.net.tr"]
    assert cfg.payments_live_allowed is False  # canlı ödeme G3 onayına kadar kapalı


def test_client_ip_with_forwarded_hops() -> None:
    """Yük dengeleyici arkasında istemci adresi: X-Forwarded-For'un sağdan n'inci değeri; istemcinin
    eklediği sahte değerler (solda) hız sınırını atlatmak için kullanılamaz."""
    from types import SimpleNamespace

    from starlette.requests import Request

    from ati_cloud.accounts import client_ip

    def request(values: list[str], hops: int, peer: str = "10.1.2.3") -> Request:
        app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(forwarded_hops=hops)))
        headers = [(b"x-forwarded-for", v.encode()) for v in values]
        return Request({"type": "http", "headers": headers, "client": (peer, 1234), "app": app})

    assert client_ip(request(["203.0.113.7"], 0)) == "10.1.2.3"  # 0: uvicorn çözer
    assert client_ip(request(["203.0.113.7"], 1)) == "203.0.113.7"
    assert client_ip(request(["1.1.1.1, 203.0.113.7"], 1)) == "203.0.113.7"  # sahte sol değer
    assert client_ip(request(["1.1.1.1", "203.0.113.7"], 1)) == "203.0.113.7"  # iki başlık
    assert client_ip(request(["203.0.113.7, 198.51.100.2"], 2)) == "203.0.113.7"
    assert client_ip(request(["2001:db8::1"], 1)) == "2001:db8::1"
    assert client_ip(request([], 1)) == "10.1.2.3"
    assert client_ip(request(["bozuk-deger"], 1)) == "10.1.2.3"


def test_database_processes_use_selector_event_loop() -> None:
    """Windows sunucusunda psycopg'nin asenkron sürücüsü ProactorEventLoop ile çalışmaz: API ve
    komut satırı araçları SelectorEventLoop kullanmalı (Windows VDS'de bulundu)."""
    import asyncio
    import inspect

    import uvicorn

    from ati_cloud import loop, server
    from ati_cloud.admin import cli as admin_cli
    from ati_cloud.licensing import cli as license_cli
    from ati_cloud.payments import cli as payments_cli

    # uvicorn'un ayarı gerçekte nasıl yorumladığı: dönen fabrika bir döngü örneği üretmeli.
    factory = uvicorn.Config(app=None, loop=loop.UVICORN_LOOP).get_loop_factory()
    assert factory is not None
    created = factory()
    try:
        assert isinstance(created, asyncio.SelectorEventLoop)
    finally:
        created.close()
    assert "loop=UVICORN_LOOP" in inspect.getsource(server.main)

    async def answer() -> str:
        return type(asyncio.get_running_loop()).__name__

    assert loop.run(answer()) in ("_UnixSelectorEventLoop", "_WindowsSelectorEventLoop")
    for module in (admin_cli, license_cli, payments_cli):
        source = inspect.getsource(module)
        assert "asyncio.run(" not in source and "return run(" in source, module.__name__


def test_api_entry_point_serves_database_requests(dsn: str) -> None:
    """Gerçek giriş noktası (ati-cloud-api → uvicorn) açılır ve veritabanından okur. Bir önceki
    sürümde yanlış döngü ayarı sunucunun hiç açılmamasına yol açtı; birim test bunu yakalamadı."""
    import os
    import socket
    import subprocess
    import sys
    import time

    import httpx

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "ATI_DATABASE_URL": dsn, "ATI_ENVIRONMENT": "test"}
    proc = subprocess.Popen(  # noqa: S603 - sabit komut, test süreci
        [sys.executable, "-c", f"from ati_cloud.server import main; main(['--port', '{port}'])"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        status = None
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                status = httpx.get(f"http://127.0.0.1:{port}/v1/plans", timeout=2).status_code
                break
            except httpx.TransportError:
                time.sleep(0.2)
        if status is None:
            proc.kill()
            output = proc.communicate()[0].decode(errors="replace")
            raise AssertionError(f"API açılmadı:\n{output[-3000:]}")
        assert status == 200
        assert httpx.get(f"http://127.0.0.1:{port}/v1/releases", timeout=5).status_code == 200
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
