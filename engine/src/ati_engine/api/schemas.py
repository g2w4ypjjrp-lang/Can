"""Yerel API istek/yanıt şemaları.

Bu modeller ``shared/protocol/engine-local-api.schema.json`` dosyasına dışa aktarılır;
masaüstü (TypeScript) ve iOS (Swift) istemcileri tiplerini bu şemadan üretir.
"""

from __future__ import annotations

from typing import Any, Literal

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


# --- Balina radarı (Aşama 4) -------------------------------------------------------------------


class WhaleTradeInfo(BaseModel):
    time_ms: int
    market: Market
    symbol: str
    side: str
    notional: float
    avg_price: float
    qty: float
    fills: int
    sweep_pct: float
    threshold: float


class WhaleAlertInfo(BaseModel):
    ts_ms: int
    market: Market | None
    symbol: str
    kind: str
    severity: str
    side: str
    notional: float
    message: str
    details: dict[str, object]


class WhaleSymbolSummary(BaseModel):
    symbol: str
    count: int
    buy_usd: float
    sell_usd: float
    net_usd: float
    largest_usd: float
    last_ms: int
    threshold_usd: float


class WhaleStatsInfo(BaseModel):
    orders_seen: int
    whale_trades: int
    alerts: int
    impact_pending: int
    ticks: int
    tick_ms_max: float
    liquidations_5m: dict[str, float]
    positioning_symbols: int
    onchain_enabled: bool


class WhaleSummaryResponse(BaseModel):
    market: Market
    window_s: int
    rows: list[WhaleSymbolSummary]
    stats: WhaleStatsInfo


class ImpactInfo(BaseModel):
    kind: str
    expected_direction: str
    horizon_s: int
    samples: int
    mean_directional_pct: float
    std_pct: float
    hit_rate: float


class PositioningInfo(BaseModel):
    symbol: str
    timestamp_ms: int
    top_long_pct: float
    top_ratio: float
    global_long_pct: float
    global_ratio: float
    open_interest_usd: float
    top_long_change_pts: float
    global_long_change_pts: float
    open_interest_change_pct: float
    divergence: bool


# --- Tarihsel veri (Aşama 5) ------------------------------------------------------------


class HistoryCoverageInfo(BaseModel):
    market: str
    symbol: str
    interval: str
    rows: int


class HistorySyncReportInfo(BaseModel):
    symbol: str
    files_downloaded: int
    files_skipped: int
    rows_inserted: int
    first_open_ms: int | None
    last_open_ms: int | None
    seconds: float


class HistoryJobInfo(BaseModel):
    id: int
    market: Market
    symbols: list[str]
    interval: str
    state: str
    started_ms: int
    finished_ms: int | None
    current: str | None
    error: str | None
    reports: list[HistorySyncReportInfo]


class HistoryStatusResponse(BaseModel):
    coverage: list[HistoryCoverageInfo]
    jobs: list[HistoryJobInfo]


class HistorySyncRequest(BaseModel):
    market: Market = Market.SPOT
    symbols: list[str] = Field(min_length=1, max_length=200)
    interval: str = "1h"


class CandlesResponse(BaseModel):
    market: Market
    symbol: str
    interval: str
    columns: list[str]
    rows: list[list[float]]


class LevelInfo(BaseModel):
    price: float
    kind: str
    touches: int
    first_time_ms: int
    last_time_ms: int
    strength: float
    distance_pct: float


class LevelsResponse(BaseModel):
    market: Market
    symbol: str
    interval: str
    bars: int
    last_close: float | None
    levels: list[LevelInfo]


class TrendLineInfo(BaseModel):
    kind: str
    a_time_ms: int
    a_price: float
    b_time_ms: int
    b_price: float
    slope_per_bar: float
    value_now: float


class TrendBreakInfo(BaseModel):
    time_ms: int
    direction: str
    close: float
    line_value: float
    penetration_atr: float
    line_kind: str


class TrendResponse(BaseModel):
    market: Market
    symbol: str
    interval: str
    bars: int
    active: list[TrendLineInfo]
    breaks: list[TrendBreakInfo]


class SimilarMatchInfo(BaseModel):
    start_time_ms: int
    end_time_ms: int
    distance: float
    forward_pct: dict[int, float]


class ForwardStatInfo(BaseModel):
    horizon_bars: int
    n: int
    mean_pct: float
    median_pct: float
    positive_rate: float


class SimilarResponse(BaseModel):
    market: Market
    symbol: str
    interval: str
    window: int
    query_end_time_ms: int
    candidates: int
    matches: list[SimilarMatchInfo]
    forward: list[ForwardStatInfo]
    disclaimer: str = "Geçmişteki benzer dönemlerin sonucudur; gelecekteki fiyatı garanti etmez."


# --- Analiz ve model (Aşama 6) ------------------------------------------------------------


class AnalysisSnapshotResponse(BaseModel):
    market: Market
    symbol: str
    interval: str
    bar_open_time_ms: int
    indicators: dict[str, Any]
    features: dict[str, float | None]


class TrainRequest(BaseModel):
    market: Market = Market.SPOT
    symbols: list[str] = Field(min_length=1, max_length=50)
    interval: str = "1h"
    horizon: int = Field(default=4, ge=1, le=500)
    side: Literal["long", "short"] = "long"
    with_futures: bool = False
    since_ms: int | None = None
    cost: float | None = Field(default=None, ge=0, le=0.05)


class TrainJobInfo(BaseModel):
    id: int
    market: Market
    symbols: list[str]
    interval: str
    horizon: int
    side: str
    with_futures: bool
    state: str
    stage: str
    started_ms: int
    finished_ms: int | None
    model_id: str | None
    oos: dict[str, Any]
    error: str | None


class ModelInfo(BaseModel):
    id: str
    created_ms: int
    market: str
    symbols: list[str]
    interval: str
    horizon: int
    side: str
    threshold: float
    cost: float
    feature_names: list[str]
    train_start_ms: int
    train_end_ms: int
    rows: int
    onnx_sha256: str
    parity_max_abs_diff: float
    oos: dict[str, Any]
    calibration: list[dict[str, Any]]
    top_features: dict[str, float]
    disclaimer: str


class PredictionResponse(BaseModel):
    model_id: str
    symbol: str
    interval: str
    side: str
    horizon_bars: int
    bar_open_time_ms: int
    probability: float
    base_rate: float | None
    oos_auc: float | None
    missing_features: list[str]
    disclaimer: str
