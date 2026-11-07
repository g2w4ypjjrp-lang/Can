"""Yerel API istek/yanıt şemaları.

Bu modeller ``shared/protocol/engine-local-api.schema.json`` dosyasına dışa aktarılır;
masaüstü (TypeScript) ve iOS (Swift) istemcileri tiplerini bu şemadan üretir.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ati_engine.core.models import EngineState, Market, TradingMode


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class KillSwitchInfo(BaseModel):
    engaged: bool
    reason: str | None = None
    actor: str | None = None
    since_ms: int | None = None


class ReadinessInfo(BaseModel):
    name: str
    ready: bool
    detail: str


class TaskInfo(BaseModel):
    name: str
    state: str
    restarts: int
    last_error: str | None = None


class LoopLagInfo(BaseModel):
    last_ms: float
    p99_ms: float
    max_ms: float


class StatusResponse(BaseModel):
    version: str
    engine_state: EngineState
    state_reason: str
    trading_mode: TradingMode
    can_open_positions: bool
    can_manage_positions: bool
    kill_switch: KillSwitchInfo
    readiness: list[ReadinessInfo]
    tasks: list[TaskInfo]
    loop_lag: LoopLagInfo
    uptime_s: float


class KillSwitchEngageRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class KillSwitchReleaseRequest(BaseModel):
    confirmation: str = Field(max_length=100)


class KillSwitchResponse(BaseModel):
    changed: bool
    kill_switch: KillSwitchInfo
    engine_state: EngineState


class TradingModeRequest(BaseModel):
    mode: TradingMode
    acknowledgement: str | None = Field(default=None, max_length=200)


class CheckInfo(BaseModel):
    name: str
    passed: bool
    message: str


class TradingModeResponse(BaseModel):
    accepted: bool
    mode: TradingMode
    checks: list[CheckInfo]


class AuditEntry(BaseModel):
    id: int
    ts: int
    actor: str
    action: str
    details: dict[str, object]


class ShutdownResponse(BaseModel):
    accepted: bool = True


class ErrorResponse(BaseModel):
    detail: str


class WsAuthMessage(BaseModel):
    type: Literal["auth"]
    token: str


class WsAuthOk(BaseModel):
    type: Literal["auth_ok"] = "auth_ok"
    version: str


# --- Piyasa verisi (Aşama 2) ---------------------------------------------------------------


class ConnectionInfo(BaseModel):
    name: str
    route: str
    url: str
    connected: bool
    healthy: bool
    streams: int
    subscribed: int
    messages: int
    reconnects: int
    last_message_age_s: float | None
    connected_for_s: float | None
    last_error: str | None


class OrderBookInfo(BaseModel):
    symbol: str
    state: str
    update_id: int
    best_bid: float | None
    best_ask: float | None
    imbalance_10: float | None
    resyncs: int
    applied: int


class RestBudgetInfo(BaseModel):
    limit_per_minute: int
    used: int
    blocked_for_s: float
    banned: bool
    waits: int
    total_used: int


class TradeGapInfo(BaseModel):
    detected: int
    recovered_trades: int
    unrecovered_gaps: int
    unrecovered_trades: int
    duplicates: int
    pending: int


class MarketServiceInfo(BaseModel):
    market: Market
    ready: bool
    tracked_symbols: int
    streams: int
    connections: list[ConnectionInfo]
    message_rates_per_s: dict[str, float]
    order_books: list[OrderBookInfo]
    trade_gaps: TradeGapInfo
    focus: list[str]
    rest_budget: RestBudgetInfo
    last_discovery_error: str | None


class MarketStatusResponse(BaseModel):
    enabled: bool
    markets: list[MarketServiceInfo]


class TickerInfo(BaseModel):
    symbol: str
    last: float
    change_pct: float
    high: float
    low: float
    quote_volume: float
    event_time_ms: int
    mark_price: float | None = None
    funding_rate: float | None = None


class TickersResponse(BaseModel):
    market: Market
    count: int
    tickers: list[TickerInfo]


class FocusRequest(BaseModel):
    market: Market
    symbols: list[str] = Field(max_length=100)


class FocusResponse(BaseModel):
    market: Market
    focus: list[str]


# --- Coin tarayıcı (Aşama 3) ---------------------------------------------------------------


class ScanRowInfo(BaseModel):
    market: Market
    symbol: str
    last_price: float | None
    change_1m_pct: float | None
    change_5m_pct: float | None
    change_15m_pct: float | None
    change_24h_pct: float | None
    quote_volume_24h: float | None
    quote_volume_60s: float
    volume_z_60s: float | None
    price_z_60s: float | None
    volatility_1m_pct: float | None
    imbalance_60s: float | None
    imbalance_300s: float | None
    buy_quote_300s: float
    sell_quote_300s: float
    spread_bps: float | None
    book_imbalance_10: float | None
    book_notional_10: float | None
    baseline_minutes: int
    listed_at_ms: int | None
    signals: list[str]
    updated_ms: int


class ScannerStatsInfo(BaseModel):
    symbols: int
    ticks: int
    tick_ms_last: float
    tick_ms_max: float
    signals: int
    warmup_done: dict[str, int]


class ScannerTopResponse(BaseModel):
    market: Market
    sort: str
    count: int
    rows: list[ScanRowInfo]
    stats: ScannerStatsInfo


class SignalInfo(BaseModel):
    ts_ms: int
    market: Market
    symbol: str
    kind: str
    severity: str
    value: float
    threshold: float
    message: str
    details: dict[str, object]
