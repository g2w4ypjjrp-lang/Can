"""Yerel kontrol API'si.

Güvenlik önlemleri:
* Yalnızca loopback adresine bağlanır (ayar doğrulaması ``config.LocalApiSettings``).
* ``/v1/health`` dışındaki her uç nokta ``Authorization: Bearer <belirteç>`` ister;
  karşılaştırma sabit zamanlıdır.
* ``Host`` başlığı yalnızca 127.0.0.1 / localhost olabilir (DNS rebinding koruması).
* Tarayıcı kaynaklı isteklerde ``Origin`` yalnızca masaüstü uygulamasının kaynağı olabilir.
* WebSocket bağlantısı ilk mesajda belirteçle kimlik doğrular; 5 saniyede doğrulamazsa kapanır.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import itertools
import json
import socket
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.websockets import WebSocketDisconnect

from ati_engine.api.schemas import (
    AuditEntry,
    CheckInfo,
    ErrorResponse,
    FocusRequest,
    FocusResponse,
    HealthResponse,
    KillSwitchEngageRequest,
    KillSwitchInfo,
    KillSwitchReleaseRequest,
    KillSwitchResponse,
    LoopLagInfo,
    MarketServiceInfo,
    MarketStatusResponse,
    ReadinessInfo,
    ScannerStatsInfo,
    ScannerTopResponse,
    ScanRowInfo,
    ShutdownResponse,
    SignalInfo,
    StatusResponse,
    TaskInfo,
    TickerInfo,
    TickersResponse,
    TradingModeRequest,
    TradingModeResponse,
    WsAuthMessage,
    WsAuthOk,
)
from ati_engine.core.bus import OverflowPolicy
from ati_engine.core.events import Event, SystemEvent, encode_event
from ati_engine.core.models import Market
from ati_engine.market.service import MarketDataService
from ati_engine.runtime import EngineRuntime
from ati_engine.safety.kill_switch import KillSwitchConfirmationError
from ati_engine.scanner.scanner import MarketScanner, row_dict

ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]", "::1"]
WS_AUTH_TIMEOUT_S = 5.0
WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_FORBIDDEN_ORIGIN = 4403
LOCAL_ACTOR = "local_api"

_ws_ids = itertools.count(1)


def _token_matches(expected: str, provided: str | None) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def require_token(request: Request) -> None:
    runtime: EngineRuntime = request.app.state.runtime
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not _token_matches(runtime.api_token, token.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya eksik belirteç",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Modül seviyesinde tanımlı olmalı: FastAPI ertelenmiş (string) tip açıklamalarını
# modülün global ad alanında çözer.
Auth = Annotated[None, Depends(require_token)]


def create_app(runtime: EngineRuntime) -> FastAPI:
    app = FastAPI(
        title="AI Trading Intelligence - Yerel Motor API",
        version=runtime.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.runtime = runtime
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime.settings.api.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def kill_switch_info() -> KillSwitchInfo:
        ks = runtime.safety.kill_switch.status
        return KillSwitchInfo(
            engaged=ks.engaged, reason=ks.reason, actor=ks.actor, since_ms=ks.since_ms
        )

    @app.get("/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(version=runtime.version)

    @app.get("/v1/status", response_model=StatusResponse)
    async def get_status(_: Auth) -> StatusResponse:
        state = runtime.safety.state
        monitor = runtime.loop_monitor
        return StatusResponse(
            version=runtime.version,
            engine_state=state.state,
            state_reason=state.reason,
            trading_mode=runtime.trading_mode.mode,
            can_open_positions=state.can_open_positions(),
            can_manage_positions=state.can_manage_positions(),
            kill_switch=kill_switch_info(),
            readiness=[
                ReadinessInfo(name=c.name, ready=c.ready, detail=c.detail)
                for c in runtime.safety.conditions()
            ],
            tasks=[
                TaskInfo(
                    name=t.name, state=t.state.value, restarts=t.restarts, last_error=t.last_error
                )
                for t in runtime.supervisor.status()
            ],
            loop_lag=LoopLagInfo(
                last_ms=monitor.last_ms, p99_ms=monitor.p99_ms(), max_ms=monitor.max_ms
            ),
            uptime_s=runtime.uptime_s,
        )

    @app.post("/v1/kill-switch/engage", response_model=KillSwitchResponse)
    async def engage_kill_switch(body: KillSwitchEngageRequest, _: Auth) -> KillSwitchResponse:
        changed = await runtime.safety.engage_kill_switch(reason=body.reason, actor=LOCAL_ACTOR)
        return KillSwitchResponse(
            changed=changed, kill_switch=kill_switch_info(), engine_state=runtime.safety.state.state
        )

    @app.post(
        "/v1/kill-switch/release",
        response_model=KillSwitchResponse,
        responses={400: {"model": ErrorResponse}},
    )
    async def release_kill_switch(body: KillSwitchReleaseRequest, _: Auth) -> KillSwitchResponse:
        try:
            changed = await runtime.safety.release_kill_switch(
                actor=LOCAL_ACTOR, confirmation=body.confirmation
            )
        except KillSwitchConfirmationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return KillSwitchResponse(
            changed=changed, kill_switch=kill_switch_info(), engine_state=runtime.safety.state.state
        )

    @app.get("/v1/trading-mode", response_model=TradingModeResponse)
    async def get_trading_mode(_: Auth) -> TradingModeResponse:
        return TradingModeResponse(accepted=True, mode=runtime.trading_mode.mode, checks=[])

    @app.post(
        "/v1/trading-mode",
        response_model=TradingModeResponse,
        responses={409: {"model": TradingModeResponse}},
    )
    async def set_trading_mode(body: TradingModeRequest, _: Auth) -> JSONResponse:
        result = await runtime.trading_mode.request_mode(
            body.mode, actor=LOCAL_ACTOR, acknowledgement=body.acknowledgement
        )
        payload = TradingModeResponse(
            accepted=result.accepted,
            mode=result.mode,
            checks=[
                CheckInfo(name=c.name, passed=c.passed, message=c.message) for c in result.checks
            ],
        )
        return JSONResponse(
            status_code=200 if result.accepted else 409, content=payload.model_dump(mode="json")
        )

    @app.get("/v1/audit", response_model=list[AuditEntry])
    async def get_audit(
        _: Auth, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> list[AuditEntry]:
        return [AuditEntry(**row) for row in await runtime.audit.recent(limit)]

    @app.post("/v1/engine/shutdown", response_model=ShutdownResponse, status_code=202)
    async def shutdown(_: Auth) -> ShutdownResponse:
        await runtime.audit.record(actor=LOCAL_ACTOR, action="engine.shutdown_requested")
        runtime.request_shutdown()
        return ShutdownResponse()

    def market_service(market: Market) -> MarketDataService:
        service = runtime.market_data.get(market)
        if service is None:
            raise HTTPException(status_code=404, detail=f"{market.value} piyasa verisi etkin değil")
        return service

    @app.get("/v1/market/status", response_model=MarketStatusResponse)
    async def market_status(_: Auth) -> MarketStatusResponse:
        return MarketStatusResponse(
            enabled=bool(runtime.market_data),
            markets=[
                MarketServiceInfo.model_validate(service.status())
                for service in runtime.market_data.values()
            ],
        )

    @app.get("/v1/market/tickers", response_model=TickersResponse)
    async def market_tickers(
        _: Auth,
        market: Market = Market.SPOT,
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
        focus_only: bool = False,
    ) -> TickersResponse:
        service = market_service(market)
        tickers = []
        for t in service.tickers(limit, focus_only=focus_only):
            mark = service.state.marks.get(t.symbol)
            tickers.append(
                TickerInfo(
                    symbol=t.symbol,
                    last=t.last,
                    change_pct=round(t.change_pct, 4),
                    high=t.high,
                    low=t.low,
                    quote_volume=t.quote_volume,
                    event_time_ms=t.event_time_ms,
                    mark_price=mark.mark_price if mark else None,
                    funding_rate=mark.funding_rate if mark else None,
                )
            )
        return TickersResponse(market=market, count=len(tickers), tickers=tickers)

    @app.post("/v1/market/focus", response_model=FocusResponse)
    async def market_focus(body: FocusRequest, _: Auth) -> FocusResponse:
        service = market_service(body.market)
        focus = service.set_focus(body.symbols)
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="market.focus",
            details={"market": body.market.value, "symbols": focus},
        )
        return FocusResponse(market=body.market, focus=focus)

    sortable = {
        "volume_z_60s",
        "price_z_60s",
        "change_1m_pct",
        "change_5m_pct",
        "change_15m_pct",
        "change_24h_pct",
        "quote_volume_60s",
        "quote_volume_24h",
        "imbalance_60s",
        "imbalance_300s",
        "volatility_1m_pct",
        "spread_bps",
    }

    def scanner_or_404() -> MarketScanner:
        if runtime.scanner is None:
            raise HTTPException(status_code=404, detail="Tarayıcı etkin değil")
        return runtime.scanner

    @app.get("/v1/scanner/top", response_model=ScannerTopResponse)
    async def scanner_top(
        _: Auth,
        market: Market = Market.SPOT,
        sort: str = "volume_z_60s",
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
        min_quote_volume_24h: Annotated[float, Query(ge=0)] = 0.0,
    ) -> ScannerTopResponse:
        scanner = scanner_or_404()
        if sort not in sortable:
            raise HTTPException(status_code=422, detail=f"Sıralama alanı: {sorted(sortable)}")
        rows = scanner.top(
            market, sort=sort, limit=limit, min_quote_volume_24h=min_quote_volume_24h
        )
        return ScannerTopResponse(
            market=market,
            sort=sort,
            count=len(rows),
            rows=[ScanRowInfo.model_validate(row_dict(r)) for r in rows],
            stats=ScannerStatsInfo.model_validate(scanner.stats()),
        )

    @app.get("/v1/scanner/signals", response_model=list[SignalInfo])
    async def scanner_signals(
        _: Auth, limit: Annotated[int, Query(ge=1, le=500)] = 100
    ) -> list[SignalInfo]:
        scanner = scanner_or_404()
        items = list(scanner.signals)[-limit:][::-1]
        return [
            SignalInfo(
                ts_ms=s.ts_ms,
                market=s.market,
                symbol=s.symbol,
                kind=s.kind.value,
                severity=s.severity.value,
                value=s.value,
                threshold=s.threshold,
                message=s.message,
                details=s.details,
            )
            for s in items
        ]

    @app.websocket("/v1/events")
    async def events(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in runtime.settings.api.allowed_origins:
            await websocket.close(code=WS_CLOSE_FORBIDDEN_ORIGIN)
            return
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT_S)
            message = WsAuthMessage.model_validate(json.loads(raw))
        except (TimeoutError, ValueError, ValidationError, WebSocketDisconnect):
            with contextlib.suppress(Exception):
                await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
            return
        if not _token_matches(runtime.api_token, message.token):
            await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
            return

        await websocket.send_text(WsAuthOk(version=runtime.version).model_dump_json())

        async def forward(event: Event) -> None:
            await websocket.send_text(encode_event(event).decode("utf-8"))

        subscription = runtime.bus.subscribe(
            SystemEvent,
            forward,
            name=f"ws-client-{next(_ws_ids)}",
            maxsize=2_000,
            policy=OverflowPolicy.DROP_OLDEST,
        )
        try:
            while True:
                incoming = await websocket.receive()
                if incoming.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await runtime.bus.unsubscribe(subscription)

    return app


class EmbeddedServer(uvicorn.Server):
    """uvicorn sunucusu; sinyal yönetimi motorun kendisine bırakılır."""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[no-untyped-def]
        yield


def bind_socket(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: başka sürecin portu ele geçirmesini önle
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.setblocking(False)
    return sock


def build_server(app: FastAPI) -> EmbeddedServer:
    config = uvicorn.Config(
        app,
        log_config=None,
        access_log=False,
        lifespan="off",
        ws_max_size=1 * 1024 * 1024,
        server_header=False,
        date_header=False,
    )
    return EmbeddedServer(config)
