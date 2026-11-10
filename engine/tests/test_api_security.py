"""Aşama 18: yerel motor API'sinin sızma testi tarzı denetimi.

Tehdit: kullanıcının tarayıcısında açık kötü niyetli bir site, ``127.0.0.1``'deki motora istek
gönderir (doğrudan, DNS yeniden bağlama ile veya WebSocket ile). Savunmalar: her uç noktada
Bearer belirteci (sabit zamanlı karşılaştırma), ``Host`` beyaz listesi, CORS ve WebSocket köken
denetimi. Tüm rotalar otomatik taranır; belirteçsiz bırakılan yeni bir uç nokta testi düşürür.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute

from ati_engine.api.server import create_app, require_token
from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings

PUBLIC = {"/v1/health"}


@dataclass
class Running:
    engine: Engine
    base_url: str
    token: str
    routes: list[tuple[str, str]]


def needs_token(route: APIRoute) -> bool:
    def walk(dependant: Any) -> bool:
        return any(dep.call is require_token or walk(dep) for dep in dependant.dependencies)

    return walk(route.dependant)


@pytest.fixture
async def running(tmp_path: Path) -> AsyncIterator[Running]:
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        heartbeat_interval_s=0.05,
        api=LocalApiSettings(port=0),
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    assert engine.runtime is not None and engine.bound_port
    app = create_app(engine.runtime)
    routes = sorted(
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    )
    yield Running(engine, f"http://127.0.0.1:{engine.bound_port}", engine.runtime.api_token, routes)
    engine.runtime.request_shutdown()
    assert await asyncio.wait_for(task, timeout=10) == 0


def concrete(path: str) -> str:
    return path.replace("{name}", "rapor.html").replace("{symbol}", "BTCUSDT")


async def test_every_route_except_health_declares_the_token(running: Running) -> None:
    assert running.engine.runtime is not None
    app = create_app(running.engine.runtime)
    unprotected = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and route.path not in PUBLIC and not needs_token(route)
    ]
    assert unprotected == []
    assert len(running.routes) >= 50


async def test_every_route_rejects_missing_wrong_and_malformed_tokens(running: Running) -> None:
    bad_headers = [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer yanlis-belirtec"},
        {"Authorization": f"Bearer {running.token[: len(running.token) // 2]}"},
        {"Authorization": f"Bearer {running.token}x"},
        {"Authorization": f"Basic {running.token}"},
        {"Authorization": running.token},
        {"X-Api-Token": running.token},
    ]
    failures = []
    async with httpx.AsyncClient(base_url=running.base_url) as client:
        for method, path in running.routes:
            if path in PUBLIC:
                continue
            for headers in bad_headers:
                response = await client.request(method, concrete(path), headers=headers)
                if response.status_code != 401:
                    failures.append(f"{method} {path} {list(headers)}: {response.status_code}")
    assert failures == []
    assert running.engine.runtime is not None
    assert not running.engine.runtime.shutdown_requested.is_set()  # kapatma işlenmedi


async def test_dns_rebinding_is_blocked_even_with_token(running: Running) -> None:
    auth = {"Authorization": f"Bearer {running.token}"}
    async with httpx.AsyncClient(base_url=running.base_url) as client:
        for host in ("kotu.example", "127.0.0.1.kotu.example", "localhost.kotu.example"):
            for path in ("/v1/status", "/v1/health", "/v1/audit"):
                response = await client.get(path, headers={**auth, "Host": host})
                assert response.status_code == 400, (host, path)
        ok = await client.get("/v1/status", headers={**auth, "Host": "localhost"})
        assert ok.status_code == 200


async def test_cors_only_for_the_desktop_shell(running: Running) -> None:
    async with httpx.AsyncClient(base_url=running.base_url) as client:
        for origin in ("https://kotu.example", "null", "http://localhost:3000"):
            preflight = await client.options(
                "/v1/kill-switch/engage",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                         "Access-Control-Request-Headers": "authorization"},
            )  # fmt: skip
            assert "access-control-allow-origin" not in preflight.headers, origin
        shell = await client.options(
            "/v1/kill-switch/engage",
            headers={"Origin": "tauri://localhost", "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "authorization"},
        )  # fmt: skip
        assert shell.headers["access-control-allow-origin"] == "tauri://localhost"
        assert "access-control-allow-credentials" not in shell.headers  # çerez yok, belirteç var


async def test_errors_do_not_leak_internals(running: Running) -> None:
    auth = {"Authorization": f"Bearer {running.token}"}
    async with httpx.AsyncClient(base_url=running.base_url) as client:
        responses = [
            await client.get("/docs"),
            await client.get("/openapi.json"),
            await client.get("/v1/backtest/reports/..%2F..%2Fengine.db", headers=auth),
            await client.get("/v1/history/candles", params={"bars": "x"}, headers=auth),
            await client.post("/v1/trading-mode", content=b"{", headers=auth),
        ]
    assert responses[0].status_code == 404 and responses[1].status_code == 404
    assert responses[2].status_code in (400, 404)
    for response in responses:
        text = response.text.lower()
        for marker in ("traceback", "sqlite", "site-packages", str(Path.home()).lower()):
            assert marker not in text, (response.request.url, marker)
