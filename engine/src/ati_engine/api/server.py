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
import time
import uuid
from typing import Annotated, Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.websockets import WebSocketDisconnect

from ati_engine.analysis.service import AnalysisService, TrainJob
from ati_engine.api.schemas import (
    AnalysisSnapshotResponse,
    AuditEntry,
    AutoTradeRequest,
    AutoTradeSettingsUpdate,
    BacktestJobInfo,
    BacktestRequest,
    CandlesResponse,
    CheckInfo,
    CrashToggle,
    DecisionInfo,
    DecisionIntervalRequest,
    ErrorResponse,
    ExecutionCloseRequest,
    ExecutionOrderInfo,
    ExecutionPositionInfo,
    ExecutionTradeResponse,
    FocusRequest,
    FocusResponse,
    ForwardStatInfo,
    HealthResponse,
    HistoryCoverageInfo,
    HistoryJobInfo,
    HistoryStatusResponse,
    HistorySyncReportInfo,
    HistorySyncRequest,
    ImpactInfo,
    KillSwitchEngageRequest,
    KillSwitchInfo,
    KillSwitchReleaseRequest,
    KillSwitchResponse,
    LevelInfo,
    LevelsResponse,
    LicenseActivateRequest,
    LicenseStatusResponse,
    LoopLagInfo,
    MarketServiceInfo,
    MarketStatusResponse,
    ModelInfo,
    OpportunityDetail,
    OpportunityStatsResponse,
    OpportunitySummary,
    PaperAccountInfo,
    PaperPositionInfo,
    PaperTradeInfo,
    PositioningInfo,
    PredictionResponse,
    ReadinessInfo,
    ReleaseDayRequest,
    RemoteToggle,
    RiskEventInfo,
    ScannerStatsInfo,
    ScannerTopResponse,
    ScanRowInfo,
    ShutdownResponse,
    SignalInfo,
    SimilarMatchInfo,
    SimilarResponse,
    StatusResponse,
    StrategyInfo,
    StrategyRegistryInfo,
    TaskInfo,
    TelegramConfig,
    TelegramDiscover,
    TestnetKeyRequest,
    TestnetKeyResponse,
    TestnetTradeRequest,
    TickerInfo,
    TickersResponse,
    TradingModeRequest,
    TradingModeResponse,
    TrainJobInfo,
    TrainRequest,
    TrendBreakInfo,
    TrendLineInfo,
    TrendResponse,
    UiError,
    WhaleAlertInfo,
    WhaleStatsInfo,
    WhaleSummaryResponse,
    WhaleSymbolSummary,
    WhaleTradeInfo,
    WsAuthMessage,
    WsAuthOk,
)
from ati_engine.backtest.engine import BacktestConfig
from ati_engine.backtest.service import BacktestJob, BacktestService
from ati_engine.core.bus import OverflowPolicy
from ati_engine.core.events import Event, SystemEvent, encode_event
from ati_engine.core.models import Market, TradingMode
from ati_engine.execution.auto import (
    DECISION_INTERVAL_KEY,
    DECISION_INTERVALS,
    EDITABLE,
    AutoTrader,
    merged_settings,
)
from ati_engine.execution.auto import ENABLED_KEY as AUTOTRADE_ENABLED_KEY
from ati_engine.execution.auto import SETTINGS_KEY as AUTOTRADE_SETTINGS_KEY
from ati_engine.execution.engine import TakeProfit, TradeIntent
from ati_engine.execution.service import ExecutionService, ExecutionUnavailable
from ati_engine.execution.venue import ExecutionBlocked
from ati_engine.history.service import HistoryService, SyncJob
from ati_engine.licensing.keys import InvalidLicenseKey
from ati_engine.licensing.manager import LicenseManager, LicenseRejected, LicenseUnavailable
from ati_engine.market.service import MarketDataService
from ati_engine.ml.registry import ModelError
from ati_engine.notify.telegram import TelegramError, TelegramNotifier
from ati_engine.observability.crash import CrashReporter
from ati_engine.paper.competition import LIVE_CANDIDATE, PaperCompetition
from ati_engine.remote.crypto import b64url
from ati_engine.remote.service import REMOTE_ENABLED_KEY, RemoteService
from ati_engine.runtime import EngineRuntime
from ati_engine.safety.kill_switch import KillSwitchConfirmationError
from ati_engine.scanner.scanner import MarketScanner, row_dict
from ati_engine.scoring.live import OpportunityEngine, top_reasons
from ati_engine.scoring.score import Opportunity
from ati_engine.storage.settings_store import SettingsStore
from ati_engine.strategies.library import ALL_STRATEGIES
from ati_engine.whales.radar import WhaleRadar

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


HistoryBars = Annotated[int, Query(ge=50, le=20_000)]


def _first_error(exc: Exception) -> str:
    """Doğrulama hatasından kullanıcıya gösterilecek ilk açıklama."""
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if errors:
            message = str(errors[0].get("msg", ""))
            return message.removeprefix("Value error, ")
    return str(exc)


# Hatalı okumayla oluşmuş günlük kilidi kaldırma onay ifadesi.
RELEASE_DAY_PHRASE = "KILIDI KALDIR"


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

    def whales_or_404() -> WhaleRadar:
        if runtime.whales is None:
            raise HTTPException(status_code=404, detail="Balina radarı etkin değil")
        return runtime.whales

    @app.get("/v1/whales/trades", response_model=list[WhaleTradeInfo])
    async def whale_trades(
        _: Auth,
        market: Market | None = None,
        symbol: str | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[WhaleTradeInfo]:
        radar = whales_or_404()
        wanted = symbol.upper() if symbol else None
        items = [
            t
            for t in reversed(radar.trades)
            if (market is None or t.market is market) and (wanted is None or t.symbol == wanted)
        ][:limit]
        return [
            WhaleTradeInfo(
                time_ms=t.event_time_ms,
                market=t.market,
                symbol=t.symbol,
                side=t.side,
                notional=t.notional,
                avg_price=t.avg_price,
                qty=t.qty,
                fills=t.fills,
                sweep_pct=t.sweep_pct,
                threshold=t.threshold,
            )
            for t in items
        ]

    @app.get("/v1/whales/alerts", response_model=list[WhaleAlertInfo])
    async def whale_alerts(
        _: Auth, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> list[WhaleAlertInfo]:
        radar = whales_or_404()
        return [
            WhaleAlertInfo(
                ts_ms=a.ts_ms,
                market=a.market,
                symbol=a.symbol,
                kind=a.kind.value,
                severity=a.severity.value,
                side=a.side,
                notional=a.notional,
                message=a.message,
                details=a.details,
            )
            for a in list(radar.alerts)[-limit:][::-1]
        ]

    @app.get("/v1/whales/summary", response_model=WhaleSummaryResponse)
    async def whale_summary(
        _: Auth,
        market: Market = Market.SPOT,
        window_s: Annotated[int, Query(ge=60, le=86_400)] = 3600,
        limit: Annotated[int, Query(ge=1, le=500)] = 20,
    ) -> WhaleSummaryResponse:
        radar = whales_or_404()
        return WhaleSummaryResponse(
            market=market,
            window_s=window_s,
            rows=[
                WhaleSymbolSummary.model_validate(r)
                for r in radar.summary(market, window_s=window_s, limit=limit)
            ],
            stats=WhaleStatsInfo.model_validate(radar.stats()),
        )

    @app.get("/v1/whales/impact", response_model=list[ImpactInfo])
    async def whale_impact(_: Auth) -> list[ImpactInfo]:
        radar = whales_or_404()
        return [ImpactInfo.model_validate(r) for r in radar.impact.summary()]

    @app.get("/v1/whales/positioning", response_model=list[PositioningInfo])
    async def whale_positioning(_: Auth) -> list[PositioningInfo]:
        radar = whales_or_404()
        return [
            PositioningInfo.model_validate(vars(s))
            for s in sorted(radar.positioning.values(), key=lambda s: -s.open_interest_usd)
        ]

    # --- Tarihsel veri (Aşama 5) ---------------------------------------------------------

    def history_or_404() -> HistoryService:
        if runtime.history is None:
            raise HTTPException(status_code=404, detail="Tarihsel veri servisi etkin değil")
        return runtime.history

    def job_info(job: SyncJob) -> HistoryJobInfo:
        return HistoryJobInfo(
            id=job.id,
            market=job.market,
            symbols=job.symbols,
            interval=job.interval,
            state=job.state,
            started_ms=job.started_ms,
            finished_ms=job.finished_ms,
            current=job.current,
            error=job.error,
            reports=[
                HistorySyncReportInfo(
                    symbol=r.symbol,
                    files_downloaded=r.files_downloaded,
                    files_skipped=r.files_skipped,
                    rows_inserted=r.rows_inserted,
                    first_open_ms=r.first_open_ms,
                    last_open_ms=r.last_open_ms,
                    seconds=r.seconds,
                )
                for r in job.reports
            ],
        )

    @app.get("/v1/history/status", response_model=HistoryStatusResponse)
    async def history_status(_: Auth) -> HistoryStatusResponse:
        history = history_or_404()
        coverage = [
            HistoryCoverageInfo(market=m, symbol=s, interval=i, rows=n)
            for m, s, i, n in await history.store.symbols()
        ]
        jobs = [job_info(j) for j in sorted(history.jobs.values(), key=lambda j: -j.id)[:20]]
        return HistoryStatusResponse(coverage=coverage, jobs=jobs)

    @app.post(
        "/v1/history/sync", response_model=HistoryJobInfo, status_code=status.HTTP_202_ACCEPTED
    )
    async def history_sync(body: HistorySyncRequest, _: Auth) -> HistoryJobInfo:
        history = history_or_404()
        symbols = [s.strip().upper() for s in body.symbols]
        if not all(s.isalnum() and len(s) <= 30 for s in symbols):
            raise HTTPException(status_code=422, detail="Geçersiz sembol")
        try:
            job = history.start_sync(body.market, symbols, body.interval)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return job_info(job)

    @app.get("/v1/history/candles", response_model=CandlesResponse)
    async def history_candles(
        _: Auth,
        symbol: str,
        market: Market = Market.SPOT,
        interval: str = "1h",
        bars: HistoryBars = 500,
    ) -> CandlesResponse:
        history = history_or_404()
        try:
            rows = await history.bars(market, symbol, interval, tail=bars)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return CandlesResponse(
            market=market,
            symbol=symbol.upper(),
            interval=interval,
            columns=["open_time", "open", "high", "low", "close", "volume"],
            rows=[[float(v) for v in r[:6]] for r in rows],
        )

    @app.get("/v1/history/levels", response_model=LevelsResponse)
    async def history_levels(
        _: Auth,
        symbol: str,
        market: Market = Market.SPOT,
        interval: str = "1h",
        bars: HistoryBars = 1000,
    ) -> LevelsResponse:
        history = history_or_404()
        try:
            rows, levels = await history.levels(market, symbol, interval, tail=bars)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return LevelsResponse(
            market=market,
            symbol=symbol.upper(),
            interval=interval,
            bars=len(rows),
            last_close=float(rows[-1][4]) if rows else None,
            levels=[LevelInfo.model_validate(vars(lv)) for lv in levels],
        )

    @app.get("/v1/history/trend", response_model=TrendResponse)
    async def history_trend(
        _: Auth,
        symbol: str,
        market: Market = Market.SPOT,
        interval: str = "1h",
        bars: HistoryBars = 1000,
    ) -> TrendResponse:
        history = history_or_404()
        try:
            rows, analysis = await history.trend(market, symbol, interval, tail=bars)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        last = len(rows) - 1
        return TrendResponse(
            market=market,
            symbol=symbol.upper(),
            interval=interval,
            bars=len(rows),
            active=[
                TrendLineInfo(
                    kind=line.kind,
                    a_time_ms=line.a_time_ms,
                    a_price=line.a_price,
                    b_time_ms=line.b_time_ms,
                    b_price=line.b_price,
                    slope_per_bar=line.slope,
                    value_now=line.value_at(last),
                )
                for line in analysis.active
            ],
            breaks=[
                TrendBreakInfo(
                    time_ms=b.time_ms,
                    direction=b.direction,
                    close=b.close,
                    line_value=b.line_value,
                    penetration_atr=b.penetration_atr,
                    line_kind=b.line.kind,
                )
                for b in analysis.breaks[-50:]
            ],
        )

    @app.get("/v1/history/similar", response_model=SimilarResponse)
    async def history_similar(
        _: Auth,
        symbol: str,
        market: Market = Market.SPOT,
        interval: str = "1h",
        bars: Annotated[int, Query(ge=200, le=200_000)] = 20_000,
        window: Annotated[int, Query(ge=8, le=500)] = 48,
        top_k: Annotated[int, Query(ge=1, le=50)] = 10,
        horizons: str = "6,24",
    ) -> SimilarResponse:
        history = history_or_404()
        try:
            steps = sorted({int(h) for h in horizons.split(",") if h.strip()})
            if not steps or steps[0] < 1 or steps[-1] > 1000:
                raise ValueError("horizons 1-1000 arası tam sayılar olmalı")
            result = await history.similar(
                market, symbol, interval, tail=bars, window=window, top_k=top_k, horizons=steps
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return SimilarResponse(
            market=market,
            symbol=symbol.upper(),
            interval=interval,
            window=result.window,
            query_end_time_ms=result.query_end_time_ms,
            candidates=result.candidates,
            matches=[
                SimilarMatchInfo(
                    start_time_ms=m.start_time_ms,
                    end_time_ms=m.end_time_ms,
                    distance=m.distance,
                    forward_pct=m.forward_pct,
                )
                for m in result.matches
            ],
            forward=[
                ForwardStatInfo(
                    horizon_bars=f.horizon,
                    n=f.n,
                    mean_pct=f.mean_pct,
                    median_pct=f.median_pct,
                    positive_rate=f.positive_rate,
                )
                for f in result.forward
            ],
        )

    # --- Analiz ve model (Aşama 6) --------------------------------------------------------

    def analysis_or_404() -> AnalysisService:
        if runtime.analysis is None:
            raise HTTPException(status_code=404, detail="Analiz servisi etkin değil")
        return runtime.analysis

    def train_job_info(job: TrainJob) -> TrainJobInfo:
        return TrainJobInfo(
            id=job.id,
            market=job.market,
            symbols=job.symbols,
            interval=job.interval,
            horizon=job.horizon,
            side=job.side,
            with_futures=job.with_futures,
            state=job.state,
            stage=job.stage,
            started_ms=job.started_ms,
            finished_ms=job.finished_ms,
            model_id=job.model_id,
            oos=job.oos,
            error=job.error,
        )

    @app.get("/v1/analysis/snapshot", response_model=AnalysisSnapshotResponse)
    async def analysis_snapshot(
        _: Auth, symbol: str, market: Market = Market.SPOT, interval: str = "1h"
    ) -> AnalysisSnapshotResponse:
        analysis = analysis_or_404()
        try:
            data = await analysis.snapshot(market, symbol, interval)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return AnalysisSnapshotResponse.model_validate(data)

    @app.post(
        "/v1/analysis/train", response_model=TrainJobInfo, status_code=status.HTTP_202_ACCEPTED
    )
    async def analysis_train(body: TrainRequest, _: Auth) -> TrainJobInfo:
        analysis = analysis_or_404()
        symbols = [s.strip().upper() for s in body.symbols]
        if not all(s.isalnum() and len(s) <= 30 for s in symbols):
            raise HTTPException(status_code=422, detail="Geçersiz sembol")
        try:
            job = analysis.start_training(
                body.market,
                symbols,
                body.interval,
                horizon=body.horizon,
                side=body.side,
                with_futures=body.with_futures,
                since_ms=body.since_ms,
                cost=body.cost,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return train_job_info(job)

    @app.get("/v1/analysis/jobs", response_model=list[TrainJobInfo])
    async def analysis_jobs(_: Auth) -> list[TrainJobInfo]:
        analysis = analysis_or_404()
        return [train_job_info(j) for j in sorted(analysis.jobs.values(), key=lambda j: -j.id)]

    @app.get("/v1/analysis/models", response_model=list[ModelInfo])
    async def analysis_models(_: Auth) -> list[ModelInfo]:
        analysis = analysis_or_404()
        return [ModelInfo.model_validate(m) for m in await asyncio.to_thread(analysis.models)]

    @app.get("/v1/analysis/predict", response_model=PredictionResponse)
    async def analysis_predict(_: Auth, model_id: str, symbol: str) -> PredictionResponse:
        analysis = analysis_or_404()
        try:
            data = await analysis.predict(model_id, symbol)
        except ModelError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return PredictionResponse.model_validate(data)

    # --- Fırsat puanı (Aşama 7) -----------------------------------------------------------

    def opportunities_or_404() -> OpportunityEngine:
        if runtime.opportunities is None:
            raise HTTPException(status_code=404, detail="Fırsat motoru etkin değil")
        return runtime.opportunities

    def opportunity_summary(opp: Opportunity) -> OpportunitySummary:
        calibration = opp.calibration or {}
        return OpportunitySummary(
            market=Market(opp.market),
            symbol=opp.symbol,
            interval=opp.interval,
            bar_open_time_ms=opp.time_ms,
            direction=opp.direction,
            score=opp.score,
            price=opp.price,
            stop_price=opp.stop_price,
            target_price=opp.target_price,
            reward_risk=opp.reward_risk,
            cost_pct=opp.cost.total_pct,
            reasons=top_reasons(opp),
            historical_hit_rate=calibration.get("hit_rate"),
            historical_net_return_pct=calibration.get("mean_net_return_pct"),
        )

    @app.get("/v1/opportunities", response_model=list[OpportunitySummary])
    async def opportunities_top(
        _: Auth,
        market: Market | None = None,
        min_score: Annotated[float, Query(ge=0, le=100)] = 0.0,
        direction: Literal["long", "short"] | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    ) -> list[OpportunitySummary]:
        engine = opportunities_or_404()
        rows = engine.top(market, min_score=min_score, direction=direction, limit=limit)
        return [opportunity_summary(o) for o in rows]

    @app.get("/v1/opportunities/detail", response_model=OpportunityDetail)
    async def opportunity_detail(
        _: Auth, symbol: str, market: Market = Market.SPOT
    ) -> OpportunityDetail:
        engine = opportunities_or_404()
        symbol = symbol.upper()
        opp = engine.latest.get((market, symbol))
        source: Literal["live", "history"] = "live"
        if opp is None:
            if runtime.history is None:
                raise HTTPException(status_code=404, detail="Bu sembol için canlı puan yok")
            try:
                opp = await engine.evaluate_from_history(runtime.history, market, symbol)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            source = "history"
        data = opp.to_dict()
        data["bar_open_time_ms"] = data.pop("time_ms")
        data["source"] = source
        return OpportunityDetail.model_validate(data)

    @app.get("/v1/opportunities/strategies", response_model=list[StrategyInfo])
    async def opportunity_strategies(_: Auth) -> list[StrategyInfo]:
        return [
            StrategyInfo(
                name=s.name,
                title=s.title,
                description=s.description,
                category=s.category,
                markets=list(s.markets),
            )
            for s in ALL_STRATEGIES
        ]

    @app.get("/v1/opportunities/reliability")
    async def opportunity_reliability(_: Auth) -> dict[str, Any]:
        """Stratejilerin sanal sonuçlara göre puandaki ağırlık çarpanı (yoksa hepsi 1)."""
        paper = runtime.paper
        return {
            "markets": {
                market.value: {
                    name: r.to_dict() for name, r in sorted(paper.reliability(market).items())
                }
                for market in Market
            }
            if paper is not None
            else {},
            "explanation": "Çarpan, stratejinin sanal yarışmadaki işlemlerinin ortalama R katından "
            "hesaplanır (az işlemde 1'e doğru küçültülür; en az 10 işlem gerekir). Sınırlar "
            "0,4-1,4. Geçmiş sanal sonuçlar gelecekteki sonuçları göstermez.",
        }

    @app.get("/v1/opportunities/calibration")
    async def opportunity_calibration(_: Auth) -> dict[str, Any]:
        engine = opportunities_or_404()
        return {
            "interval": engine.cfg.interval,
            "horizon_bars": engine.cfg.horizon_bars,
            "markets": engine.calibration,
        }

    @app.get("/v1/opportunities/stats", response_model=OpportunityStatsResponse)
    async def opportunity_stats(_: Auth) -> OpportunityStatsResponse:
        engine = opportunities_or_404()
        return OpportunityStatsResponse(
            interval=engine.cfg.interval,
            horizon_bars=engine.cfg.horizon_bars,
            publish_min_score=engine.cfg.publish_min_score,
            bars=engine.stats.bars,
            scored=engine.stats.scored,
            published=engine.stats.published,
            symbols=len(engine.books),
            warmup_symbols=engine.stats.warmup_symbols,
            warmup_total=engine.stats.warmup_total,
            batch_ms_max=round(engine.stats.batch_ms_max, 3),
            incomplete_bars=engine.aggregator.incomplete,
            repaired_bars=engine.stats.repaired,
            repair_failed=engine.stats.repair_failed,
            calibration_loaded={m: bool(c) for m, c in engine.calibration.items()},
            models_loaded={m.value: sorted(p) for m, p in engine.predictors.items()},
        )

    # --- Backtest ve strateji kayıt defteri (Aşama 8) --------------------------------------

    def backtests_or_404() -> BacktestService:
        if runtime.backtests is None:
            raise HTTPException(status_code=404, detail="Backtest servisi etkin değil")
        return runtime.backtests

    def backtest_job_info(job: BacktestJob) -> BacktestJobInfo:
        return BacktestJobInfo.model_validate(vars(job))

    @app.post(
        "/v1/backtest/run", response_model=BacktestJobInfo, status_code=status.HTTP_202_ACCEPTED
    )
    async def backtest_run(body: BacktestRequest, _: Auth) -> BacktestJobInfo:
        service = backtests_or_404()
        symbols = [s.strip().upper() for s in body.symbols]
        if not all(s.isalnum() and len(s) <= 30 for s in symbols):
            raise HTTPException(status_code=422, detail="Geçersiz sembol")
        futures = body.market is Market.USDM_FUTURES
        config = BacktestConfig(
            market="usdm_futures" if futures else "spot",
            risk_per_trade=body.risk_per_trade,
            max_positions=body.max_positions,
            max_leverage=body.leverage if futures else 1.0,
            max_hold_bars=body.max_hold_bars,
        )
        try:
            job = service.start(
                body.market.value,
                symbols,
                body.interval,
                since_ms=body.since_ms,
                walk_forward=body.walk_forward,
                config=config,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return backtest_job_info(job)

    @app.get("/v1/backtest/jobs", response_model=list[BacktestJobInfo])
    async def backtest_jobs(_: Auth) -> list[BacktestJobInfo]:
        service = backtests_or_404()
        return [backtest_job_info(j) for j in sorted(service.jobs.values(), key=lambda j: -j.id)]

    @app.get("/v1/backtest/reports", response_model=list[str])
    async def backtest_reports(_: Auth) -> list[str]:
        return backtests_or_404().reports()

    @app.get("/v1/backtest/reports/{name}")
    async def backtest_report(name: str, _: Auth) -> dict[str, Any]:
        service = backtests_or_404()
        try:
            return await asyncio.to_thread(service.report, name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Rapor bulunamadı") from exc

    @app.get("/v1/strategies", response_model=list[StrategyRegistryInfo])
    async def strategy_registry(_: Auth) -> list[StrategyRegistryInfo]:
        service = backtests_or_404()
        return [StrategyRegistryInfo.model_validate(s) for s in await service.strategies()]

    # --- Sanal işlem yarışması (Aşama 9) ---------------------------------------------------

    def paper_or_404() -> PaperCompetition:
        if runtime.paper is None:
            raise HTTPException(status_code=404, detail="Sanal işlem yarışması etkin değil")
        return runtime.paper

    @app.get("/v1/paper/leaderboard", response_model=list[PaperAccountInfo])
    async def paper_leaderboard(_: Auth, market: Market | None = None) -> list[PaperAccountInfo]:
        paper = paper_or_404()
        stages = {
            str(r[0]): str(r[1])
            for r in await runtime.db.fetchall("SELECT name, stage FROM strategies")
        }
        rows = await asyncio.to_thread(paper.leaderboard, market)
        return [
            PaperAccountInfo.model_validate({**r, "stage": stages.get(r["strategy"])}) for r in rows
        ]

    @app.get("/v1/paper/positions", response_model=list[PaperPositionInfo])
    async def paper_positions(
        _: Auth, market: Market | None = None, strategy: str | None = None
    ) -> list[PaperPositionInfo]:
        paper = paper_or_404()
        result = []
        for (name, account_market), account in paper.accounts.items():
            if (market is not None and account_market is not market) or (
                strategy is not None and name != strategy
            ):
                continue
            for symbol, t in account.positions.items():
                last = paper.last_price.get((account_market, symbol), t.entry_price)
                result.append(
                    PaperPositionInfo(
                        strategy=name,
                        market=account_market.value,
                        symbol=symbol,
                        direction="long" if t.direction > 0 else "short",
                        qty=t.qty,
                        entry_price=t.entry_price,
                        entry_time_ms=t.entry_time_ms,
                        stop=t.stop,
                        target=t.target,
                        last_price=last,
                        unrealized_pnl=round(t.unrealized(last), 6),
                        fees=t.fees,
                        funding=t.funding,
                        bars_held=t.bars_held,
                        reason=t.reason,
                    )
                )
        return result

    @app.get("/v1/paper/trades", response_model=list[PaperTradeInfo])
    async def paper_trades(
        _: Auth,
        market: Market | None = None,
        strategy: str | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 200,
    ) -> list[PaperTradeInfo]:
        paper = paper_or_404()
        rows = []
        for (name, account_market), account in paper.accounts.items():
            if (market is not None and account_market is not market) or (
                strategy is not None and name != strategy
            ):
                continue
            for t in account.trades:
                rows.append(
                    PaperTradeInfo(
                        strategy=name,
                        market=account_market.value,
                        symbol=t.symbol,
                        direction="long" if t.direction > 0 else "short",
                        qty=t.qty,
                        entry_price=t.entry_price,
                        entry_time_ms=t.entry_time_ms,
                        exit_price=t.exit_price,
                        exit_time_ms=t.exit_time_ms,
                        exit_reason=t.exit_reason,
                        fees=t.fees,
                        funding=t.funding,
                        net_pnl=round(t.net_pnl, 6),
                        r_multiple=round(t.r_multiple, 4),
                        reason=t.reason,
                    )
                )
        rows.sort(key=lambda r: -(r.exit_time_ms or 0))
        return rows[:limit]

    @app.get("/v1/paper/stats")
    async def paper_stats(_: Auth) -> dict[str, Any]:
        paper = paper_or_404()
        return {
            **paper.stats,
            "accounts": len(paper.accounts),
            "open_positions": sum(len(a.positions) for a in paper.accounts.values()),
            "settings": paper.cfg.model_dump(),
            "live_candidate_rule": LIVE_CANDIDATE,
            "disclaimer": "Sanal işlemdir; gerçek emir gönderilmez. Sonuçlar garanti değildir.",
        }

    # --- Emir yürütme: Binance test ağı (Aşama 10) --------------------------------------------

    def execution_or_404() -> ExecutionService:
        """İşlem moduna göre etkin servis: gerçek hesap modunda gerçek hesap, aksi halde Demo."""
        service = runtime.active_execution()
        if service is None:
            raise HTTPException(status_code=404, detail="Emir yürütme servisi etkin değil")
        return service

    def service_for(environment: Literal["testnet", "live"] | None) -> ExecutionService:
        if environment is None:
            return execution_or_404()
        service = runtime.execution_live if environment == "live" else runtime.execution
        if service is None:
            raise HTTPException(status_code=404, detail="Emir yürütme servisi etkin değil")
        return service

    @app.get("/v1/execution/status")
    async def execution_status(
        _: Auth, environment: Literal["testnet", "live"] | None = None
    ) -> dict[str, Any]:
        return await service_for(environment).status()

    async def store_key(service: ExecutionService, body: TestnetKeyRequest) -> TestnetKeyResponse:
        try:
            check, stored = await service.store_key(
                body.market,
                body.api_key.get_secret_value(),
                body.secret.get_secret_value(),
                actor=LOCAL_ACTOR,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        message = check.message
        if stored is not None:
            try:
                await service.connect(body.market)
            except ExecutionUnavailable as exc:
                message = f"{message}; bağlantı kurulamadı: {exc}"
        return TestnetKeyResponse(
            verified=check.ok,
            stored=stored is not None,
            message=message,
            key_hint=stored.api_key_hint if stored else None,
            can_trade=check.can_trade,
        )

    @app.post("/v1/execution/testnet-key", response_model=TestnetKeyResponse)
    async def execution_testnet_key(body: TestnetKeyRequest, _: Auth) -> TestnetKeyResponse:
        return await store_key(service_for("testnet"), body)

    @app.post("/v1/execution/testnet-key/delete")
    async def execution_delete_key(market: Market, _: Auth) -> dict[str, Any]:
        removed = await service_for("testnet").delete_key(market, actor=LOCAL_ACTOR)
        return {"removed": removed}

    @app.post("/v1/execution/live-key", response_model=TestnetKeyResponse)
    async def execution_live_key(body: TestnetKeyRequest, _: Auth) -> TestnetKeyResponse:
        """Gerçek hesap anahtarı: para çekme/transfer yetkisi açıksa reddedilir, saklanmaz."""
        return await store_key(service_for("live"), body)

    @app.post("/v1/execution/live-key/delete")
    async def execution_delete_live_key(market: Market, _: Auth) -> dict[str, Any]:
        if (
            runtime.trading_mode.mode is TradingMode.LIVE
            and runtime.execution_live is not None
            and market in runtime.execution_live.markets
            and runtime.execution_live.markets[market].engine.positions.positions
        ):
            raise HTTPException(
                status_code=409,
                detail="Açık gerçek hesap pozisyonu varken anahtar silinemez; önce kapatın",
            )
        removed = await service_for("live").delete_key(market, actor=LOCAL_ACTOR)
        return {"removed": removed}

    @app.post("/v1/execution/connect")
    async def execution_connect(
        market: Market, _: Auth, environment: Literal["testnet", "live"] | None = None
    ) -> dict[str, Any]:
        service = service_for(environment)
        try:
            await service.connect(market)
        except ExecutionUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return await service.status()

    @app.post("/v1/execution/trades", response_model=ExecutionTradeResponse)
    async def execution_open(body: TestnetTradeRequest, _: Auth) -> ExecutionTradeResponse:
        service = execution_or_404()
        intent = TradeIntent(
            decision_id=f"elle-{uuid.uuid4().hex[:24]}",
            market=body.market,
            symbol=body.symbol,
            direction=1 if body.direction == "long" else -1,
            quantity=body.quantity,
            reference_price=body.reference_price,
            stop_loss=body.stop_loss,
            take_profits=tuple(TakeProfit(t.price, t.fraction) for t in body.take_profits),
            trailing_callback_pct=body.trailing_callback_pct,
            trailing_activation=body.trailing_activation,
            leverage=body.leverage,
            limit_price=body.limit_price,
            breakeven_after_first_tp=body.breakeven_after_first_tp,
            reason=body.reason,
        )
        try:
            managed = await service.open(intent, actor=LOCAL_ACTOR)
        except (ExecutionBlocked, ExecutionUnavailable) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ExecutionTradeResponse(
            decision_id=intent.decision_id,
            state=managed.state,
            filled_qty=managed.filled_qty,
            protection_orders=len(managed.protection),
            error=managed.error,
        )

    @app.get("/v1/execution/positions", response_model=list[ExecutionPositionInfo])
    async def execution_positions(_: Auth) -> list[ExecutionPositionInfo]:
        return [ExecutionPositionInfo.model_validate(p) for p in execution_or_404().positions()]

    @app.get("/v1/execution/orders", response_model=list[ExecutionOrderInfo])
    async def execution_orders(_: Auth, open_only: bool = True) -> list[ExecutionOrderInfo]:
        rows = execution_or_404().orders(open_only=open_only)
        return [ExecutionOrderInfo.model_validate(r) for r in rows]

    @app.post("/v1/execution/close")
    async def execution_close(body: ExecutionCloseRequest, _: Auth) -> dict[str, Any]:
        try:
            record = await execution_or_404().close_position(
                body.market, body.symbol, actor=LOCAL_ACTOR, reason=body.reason
            )
        except ExecutionUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "closed": record is not None,
            "status": record.status.value if record else None,
            "executed_qty": str(record.executed_qty) if record else None,
        }

    @app.post("/v1/execution/close-all")
    async def execution_close_all(_: Auth, reason: str = "acil kapatma") -> dict[str, Any]:
        closed = await execution_or_404().close_all(reason=reason[:200], actor=LOCAL_ACTOR)
        return {"closed": closed}

    @app.post("/v1/execution/reconcile")
    async def execution_reconcile(market: Market, _: Auth) -> dict[str, Any]:
        try:
            report = await execution_or_404().reconcile(market)
        except ExecutionUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return report.as_dict()

    # --- Risk yönetimi ve otomatik işlem (Aşama 11) ---------------------------------------------

    @app.get("/v1/risk/status")
    async def risk_status(_: Auth) -> dict[str, Any]:
        service = execution_or_404()
        if service.markets:
            # Ana ekrandaki Binance bakiyesi güncel olsun (15 sn'den eskiyse yenilenir).
            with contextlib.suppress(Exception):
                await service.monitor.snapshot(max_age_s=15)
        status_ = await service.status()
        return {
            **status_["risk"],
            "engine_state": runtime.safety.state.state.value,
            "conditions": [
                {"name": c.name, "ready": c.ready, "detail": c.detail}
                for c in runtime.safety.conditions()
            ],
        }

    @app.post("/v1/risk/release-day")
    async def risk_release_day(body: ReleaseDayRequest, _: Auth) -> dict[str, Any]:
        """Günlük kilidi kaldırır. Yalnızca güncel günlük zarar sınırın altındayken (ör. aktarım
        ya da anlık hatalı okumayla oluşmuş kilit) ve onay ifadesiyle; denetim kaydına yazılır."""
        if body.confirmation.strip().upper() != RELEASE_DAY_PHRASE:
            raise HTTPException(status_code=422, detail=f"Onay için '{RELEASE_DAY_PHRASE}' yazın")
        service = execution_or_404()
        snapshot = await service.monitor.refresh()
        if snapshot.halted_at is None:
            raise HTTPException(status_code=409, detail="Gün kilitli değil")
        limit = service.settings.risk.max_daily_loss_pct
        if snapshot.daily_loss_pct >= limit:
            raise HTTPException(
                status_code=409,
                detail=f"Günlük zarar %{snapshot.daily_loss_pct:.2f}, sınır %{limit}: kilit "
                "kaldırılamaz; yeni UTC gününde (03:00) kendiliğinden açılır",
            )
        await service.monitor.release_day()
        if service.guard is not None:
            await service.guard.check()
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="risk.day_released",
            details={
                "mode": service.mode.value,
                "reason": snapshot.halt_reason,
                "daily_loss_pct": float(snapshot.daily_loss_pct),
            },
        )
        return {"released": True}

    @app.get("/v1/risk/events", response_model=list[RiskEventInfo])
    async def risk_events(
        _: Auth, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> list[RiskEventInfo]:
        rows = await runtime.db.fetchall(
            "SELECT id, ts, rule, severity, market, symbol, action, details FROM risk_events "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            RiskEventInfo(
                id=r[0],
                ts_ms=r[1],
                rule=r[2],
                severity=r[3],
                market=r[4],
                symbol=r[5],
                action=r[6],
                details=json.loads(r[7]),
            )
            for r in rows
        ]

    @app.get("/v1/risk/decisions", response_model=list[DecisionInfo])
    async def risk_decisions(
        _: Auth, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> list[DecisionInfo]:
        rows = await runtime.db.fetchall(
            "SELECT id, created_at, mode, market, symbol, direction, opportunity_score, "
            "risk_verdict, risk_reasons, outcome, features FROM decisions "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        result = []
        for r in rows:
            reasons = json.loads(r[8])
            if isinstance(reasons, list):  # eski kayıt biçimi
                reasons = {"reasons": reasons, "metrics": {}}
            features = json.loads(r[10])
            result.append(
                DecisionInfo(
                    id=r[0],
                    created_ms=r[1],
                    mode=r[2],
                    market=r[3],
                    symbol=r[4],
                    direction=r[5],
                    opportunity_score=r[6],
                    risk_verdict=r[7],
                    risk_reasons=reasons.get("reasons", []),
                    risk_metrics=reasons.get("metrics", {}),
                    outcome=r[9],
                    reason=features.get("reason") if isinstance(features, dict) else None,
                )
            )
        return result

    def autotrader_or_404() -> AutoTrader:
        if runtime.autotrader is None:
            raise HTTPException(status_code=404, detail="Otomatik işlem etkin değil")
        return runtime.autotrader

    market_names = {Market.SPOT: "Spot", Market.USDM_FUTURES: "Futures"}

    async def autotrade_checks(trader: AutoTrader) -> list[dict[str, Any]]:
        """Botun işlem açabilmesi için gerekenler; her madde arayüzde düzeltme sayfasına
        bağlanır. Sıra, kullanıcının yapacağı sıradır."""
        checks: list[dict[str, Any]] = []

        def add(key: str, ok: bool, title: str, detail: str, page: str) -> None:
            checks.append({"key": key, "ok": ok, "title": title, "detail": detail, "page": page})

        if runtime.license is not None and runtime.license.settings.enforce:
            valid = runtime.license.valid
            add("license", valid, "Lisans", "Etkin" if valid else "Lisans anahtarı girin",
                "license")  # fmt: skip
        mode = runtime.trading_mode.mode
        add(
            "mode",
            mode is not TradingMode.PAPER,
            "İşlem modu",
            {
                TradingMode.PAPER: (
                    "Sanal modda bot işlem açmaz. Uygulama her açılışta güvenlik için Sanal "
                    "başlar; Gerçek para ya da Demo'yu seçin"
                ),
                TradingMode.TESTNET: "Demo para (sahte bakiye)",
                TradingMode.LIVE: "GERÇEK PARA",
            }[mode],
            "settings",
        )
        execution = runtime.active_execution()
        info = await execution.status() if execution is not None else {"markets": {}}
        account = "gerçek hesap" if mode is TradingMode.LIVE else "Demo Trading"
        # Sanal modda anahtar maddesi gösterilmez (mod maddesi zaten eksik); hangi hesabın
        # anahtarı gerektiği mod seçilince belli olur.
        for market in trader.cfg.markets if mode is not TradingMode.PAPER else ():
            entry = info["markets"].get(market.value) or {}
            connected = bool(entry.get("connected"))
            if connected:
                detail = "Bağlı"
            elif entry.get("error"):
                detail = str(entry["error"])[:160]
            elif entry.get("key_stored"):
                detail = "Anahtar kayıtlı; bağlanılıyor"
            else:
                detail = f"Ayarlar'dan {account} anahtarı ekleyin"
            add(f"keys.{market.value}", connected,
                f"Binance {market_names[market]} ({account})", detail, "settings")  # fmt: skip
        conditions = {c.name: c for c in runtime.safety.conditions()}
        for market in trader.cfg.markets:
            cond = conditions.get(f"market_data.{market.value}")
            if cond is not None:
                add(f"data.{market.value}", cond.ready,
                    f"{market_names[market]} piyasa verisi",
                    "Akıyor" if cond.ready else cond.detail, "markets")  # fmt: skip
        engine = runtime.opportunities
        if engine is not None:
            for market in trader.cfg.markets:
                total = engine.stats.warmup_total.get(market.value)
                done = engine.stats.warmup_symbols.get(market.value, 0)
                ready = total is not None and done >= total
                detail = (
                    f"{done} coin puanlandı"
                    if ready
                    else (f"Hazırlanıyor: {done} / {total} coin" if total else "Başlıyor")
                )
                add(f"warmup.{market.value}", ready,
                    f"{market_names[market]} fırsat taraması", detail, "opportunities")  # fmt: skip
        ks = runtime.safety.kill_switch.status
        add("kill_switch", not ks.engaged, "Acil durdurma",
            "Kapalı" if not ks.engaged else f"Devrede: {ks.reason}", "dashboard")  # fmt: skip
        state = runtime.safety.state
        add("engine", state.can_open_positions(), "Motor",
            "Çalışıyor" if state.can_open_positions() else state.reason, "dashboard")  # fmt: skip
        if trader.paused_until_ms is not None and trader.paused_until_ms > int(time.time() * 1000):
            add("loss_pause", False, "Kayıp molası",
                "Art arda kayıptan sonra mola; süre bitince sürer", "bot")  # fmt: skip
        add("enabled", trader.enabled, "Bot",
            "Çalışıyor" if trader.enabled else "Botu başlatın", "dashboard")  # fmt: skip
        return checks

    async def autotrade_view(trader: AutoTrader, **extra: Any) -> dict[str, Any]:
        status = trader.status()
        checks = await autotrade_checks(trader)
        status["checks"] = checks
        status["ready"] = all(c["ok"] for c in checks)
        saved = await SettingsStore(runtime.db).get(DECISION_INTERVAL_KEY)
        status["decision_interval_saved"] = saved if saved in DECISION_INTERVALS else None
        status["restart_required"] = saved in DECISION_INTERVALS and saved != trader.interval
        status.update(extra)
        return status

    @app.get("/v1/autotrade")
    async def autotrade_status(_: Auth) -> dict[str, Any]:
        return await autotrade_view(autotrader_or_404())

    @app.post("/v1/autotrade")
    async def autotrade_toggle(body: AutoTradeRequest, _: Auth) -> dict[str, Any]:
        trader = autotrader_or_404()
        was = trader.enabled
        trader.enabled = body.enabled
        await SettingsStore(runtime.db).set(AUTOTRADE_ENABLED_KEY, body.enabled)
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="autotrade.toggle",
            details={"enabled": body.enabled, "environment": runtime.trading_mode.mode.value},
        )
        # Açılışta son mumun hâlâ taze sinyalleri hemen değerlendirilir (saat başı beklenmez).
        opened = await trader.replay() if body.enabled and not was else 0
        return await autotrade_view(trader, replayed_opened=opened)

    @app.post("/v1/autotrade/settings")
    async def autotrade_settings(body: AutoTradeSettingsUpdate, _: Auth) -> dict[str, Any]:
        """Bot ayarlarını değiştirir (kalıcı). Risk sınırları aşılamaz; gerçek hesap kilitli."""
        trader = autotrader_or_404()
        changes = body.model_dump(mode="json", exclude_none=True)
        if not changes:
            raise HTTPException(status_code=422, detail="Değişiklik yok")
        try:
            cfg = merged_settings(trader.cfg, trader.limits, changes)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=_first_error(exc)) from exc
        before = {k: v for k, v in trader.cfg.model_dump(mode="json").items() if k in EDITABLE}
        after = {k: v for k, v in cfg.model_dump(mode="json").items() if k in EDITABLE}
        await SettingsStore(runtime.db).set(AUTOTRADE_SETTINGS_KEY, after)
        trader.cfg = cfg
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="autotrade.settings_changed",
            details={"before": before, "after": after},
        )
        return await autotrade_view(trader)

    @app.post("/v1/autotrade/interval")
    async def autotrade_interval(body: DecisionIntervalRequest, _: Auth) -> dict[str, Any]:
        """Karar aralığını kaydeder; motor yeniden başlayınca uygulanır (fırsat taraması o
        aralığın mumlarıyla yeniden ısınır)."""
        trader = autotrader_or_404()
        await SettingsStore(runtime.db).set(DECISION_INTERVAL_KEY, body.interval)
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="autotrade.interval_changed",
            details={"before": trader.interval, "after": body.interval},
        )
        return await autotrade_view(trader)

    @app.post("/v1/autotrade/settings/reset")
    async def autotrade_settings_reset(_: Auth) -> dict[str, Any]:
        trader = autotrader_or_404()
        await SettingsStore(runtime.db).set(AUTOTRADE_SETTINGS_KEY, None)
        trader.cfg = trader.defaults
        await runtime.audit.record(actor=LOCAL_ACTOR, action="autotrade.settings_reset")
        return await autotrade_view(trader)

    # --- Hata raporları (isteğe bağlı) --------------------------------------------------------

    def crash_or_404() -> CrashReporter:
        if runtime.crash is None:
            raise HTTPException(status_code=404, detail="Hata raporu servisi etkin değil")
        return runtime.crash

    @app.get("/v1/crash-reports")
    async def crash_status(_: Auth) -> dict[str, Any]:
        return crash_or_404().status()

    @app.post("/v1/crash-reports/enabled")
    async def crash_toggle(body: CrashToggle, _: Auth) -> dict[str, Any]:
        reporter = crash_or_404()
        await reporter.set_enabled(body.enabled)
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="crash_reports.enabled" if body.enabled else "crash_reports.disabled",
            details={},
        )
        return reporter.status()

    @app.post("/v1/crash-reports/ui")
    async def crash_ui(body: UiError, _: Auth) -> dict[str, bool]:
        queued = crash_or_404().capture("desktop-ui", body.error_type, body.message, body.stack)
        return {"queued": queued}

    # --- Telegram bildirimleri ------------------------------------------------------------------

    def telegram_or_404() -> TelegramNotifier:
        if runtime.telegram is None:
            raise HTTPException(status_code=404, detail="Bildirim servisi etkin değil")
        return runtime.telegram

    @app.get("/v1/notifications/telegram")
    async def telegram_status(_: Auth) -> dict[str, Any]:
        return telegram_or_404().status()

    @app.post("/v1/notifications/telegram")
    async def telegram_configure(body: TelegramConfig, _: Auth) -> dict[str, Any]:
        notifier = telegram_or_404()
        try:
            await notifier.configure(
                token=body.bot_token or None,
                chat_id=body.chat_id or None,
                enabled=body.enabled,
                categories=body.categories,
            )
        except TelegramError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="notify.telegram_configured",
            details={"enabled": body.enabled, "categories": body.categories,
                     "token_changed": bool(body.bot_token)},
        )  # fmt: skip
        return notifier.status()

    @app.post("/v1/notifications/telegram/test")
    async def telegram_test(_: Auth) -> dict[str, Any]:
        notifier = telegram_or_404()
        try:
            await notifier.send_now(
                "✅ AI Trading Intelligence: Telegram bildirimleri çalışıyor.\n"
                "Acil durdurma, pozisyon açılış/kapanışları ve uyarılar buraya gelecek."
            )
        except TelegramError as exc:
            notifier.last_error = str(exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return notifier.status()

    @app.post("/v1/notifications/telegram/discover")
    async def telegram_discover(body: TelegramDiscover, _: Auth) -> list[dict[str, str]]:
        try:
            return await telegram_or_404().discover(body.bot_token)
        except TelegramError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/notifications/telegram/remove")
    async def telegram_clear(_: Auth) -> dict[str, Any]:
        notifier = telegram_or_404()
        await notifier.clear()
        await runtime.audit.record(actor=LOCAL_ACTOR, action="notify.telegram_removed")
        return notifier.status()

    # --- Uzaktan kontrol: telefon eşleştirme (Aşama 13) -----------------------------------------

    def remote_or_404() -> RemoteService:
        if runtime.remote is None:
            raise HTTPException(status_code=404, detail="Uzaktan kontrol etkin değil")
        return runtime.remote

    @app.get("/v1/remote/status")
    async def remote_status(_: Auth) -> dict[str, Any]:
        return await remote_or_404().status()

    @app.post("/v1/remote/enabled")
    async def remote_enable(body: RemoteToggle, _: Auth) -> dict[str, Any]:
        """Telefondan kontrolü aç/kapat. Seçim saklanır; motor yeniden başlayınca da geçerlidir.
        Telefondan yapılabilecekler sınırlıdır (acil durdurma, bot durdur/başlat, pozisyon
        kapatma); yeni işlem açma ve para çekme yoktur."""
        service = remote_or_404()
        if body.enabled:
            service.start()
        else:
            await service.disable()
        await SettingsStore(runtime.db).set(REMOTE_ENABLED_KEY, body.enabled)
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="remote.enabled" if body.enabled else "remote.disabled",
            details={"relay_url": service.relay_url},
        )
        return await service.status()

    @app.post("/v1/remote/pairing")
    async def remote_pairing(_: Auth) -> dict[str, Any]:
        service = remote_or_404()
        if not service.enabled or not service.relay_url:
            raise HTTPException(status_code=409, detail="Önce telefondan kontrolü açın")
        if not service.connected:
            raise HTTPException(
                status_code=409,
                detail="Aktarma servisine henüz bağlanılamadı; internet bağlantısını kontrol edin",
            )
        payload, expires = service.pairing.start(service.relay_url)
        await runtime.audit.record(actor=LOCAL_ACTOR, action="remote.pairing_started")
        # QR: telefon sayfasının adresi; eşleştirme bilgisi # sonrasında (tarayıcı sunucuya
        # göndermez). Kamera uygulaması doğrudan açar.
        url = f"{runtime.settings.remote.phone_web_url}#p={b64url(payload.encode('utf-8'))}"
        return {"qr": url, "payload": payload, "expires_ms": expires}

    @app.post("/v1/remote/devices/revoke")
    async def remote_revoke(device_id: str, _: Auth) -> dict[str, Any]:
        service = remote_or_404()
        revoked = await service.registry.revoke(device_id, int(time.time() * 1000))
        await runtime.audit.record(
            actor=LOCAL_ACTOR, action="remote.device_revoked", details={"device_id": device_id}
        )
        return {"revoked": revoked}

    @app.get("/v1/remote/commands")
    async def remote_commands(
        _: Auth, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> list[dict[str, Any]]:
        return await remote_or_404().commands(limit)

    # --- Lisans (Aşama 15) ------------------------------------------------------------------------

    def license_or_404() -> LicenseManager:
        if runtime.license is None:
            raise HTTPException(status_code=404, detail="Lisans modülü etkin değil")
        return runtime.license

    def license_http_error(exc: LicenseRejected) -> HTTPException:
        status = exc.status if exc.status in (400, 401, 403, 404, 409, 429) else 400
        return HTTPException(status_code=status, detail=exc.message)

    @app.get("/v1/license", response_model=LicenseStatusResponse)
    async def license_status(_: Auth) -> dict[str, Any]:
        return license_or_404().status()

    @app.post("/v1/license/activate", response_model=LicenseStatusResponse)
    async def license_activate(body: LicenseActivateRequest, _: Auth) -> dict[str, Any]:
        manager = license_or_404()
        try:
            status = await manager.activate(body.key)
        except InvalidLicenseKey as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LicenseRejected as exc:
            await runtime.audit.record(
                actor=LOCAL_ACTOR, action="license.activation_failed", details={"code": exc.code}
            )
            raise license_http_error(exc) from exc
        except LicenseUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # Anahtarın kendisi denetim kaydına yazılmaz; yalnızca ipucu.
        await runtime.audit.record(
            actor=LOCAL_ACTOR,
            action="license.activated",
            details={"key_hint": status["key_hint"], "plan": status["plan_code"]},
        )
        return status

    @app.post("/v1/license/refresh", response_model=LicenseStatusResponse)
    async def license_refresh(_: Auth) -> dict[str, Any]:
        return await license_or_404().refresh()

    @app.post("/v1/license/deactivate", response_model=LicenseStatusResponse)
    async def license_deactivate(_: Auth) -> dict[str, Any]:
        manager = license_or_404()
        try:
            status = await manager.deactivate()
        except LicenseRejected as exc:
            raise license_http_error(exc) from exc
        except LicenseUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=f"{exc}. Bilgisayarı müşteri panelinden de kaldırabilirsiniz.",
            ) from exc
        await runtime.audit.record(actor=LOCAL_ACTOR, action="license.deactivated")
        return status

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
