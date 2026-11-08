/* Otomatik üretildi: shared/protocol/engine-local-api.schema.json — elle düzenlemeyin.
 * Yeniden üretmek için: npm run gen:types */

/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "Severity".
 */
export type Severity = "critical" | "info" | "warning";
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "Market".
 */
export type Market = "spot" | "usdm_futures";
export type Market1 = "spot" | "usdm_futures";
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "EngineEvent".
 */
export type EngineEvent =
  | EngineStateChanged
  | TradingModeChanged
  | KillSwitchEngaged
  | KillSwitchReleased
  | ReadinessChanged
  | ServiceHealthChanged
  | Heartbeat
  | Alert
  | SymbolListed
  | SymbolDelisted
  | StreamConnectionChanged
  | OrderBookResynced
  | MarketSignal
  | WhaleAlert
  | OpportunityScored
  | PaperTradeEvent;
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "EngineState".
 */
export type EngineState = "halted" | "running" | "safe_mode" | "starting" | "stopped" | "stopping";
/**
 * İşlem modu. Varsayılan her zaman PAPER'dır (sanal işlem).
 *
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TradingMode".
 */
export type TradingMode = "live" | "paper" | "testnet";
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "SignalKind".
 */
export type SignalKind =
  "flow_imbalance" | "liquidity_drop" | "new_listing" | "price_move" | "volume_spike";
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WhaleAlertKind".
 */
export type WhaleAlertKind =
  | "accumulation"
  | "distribution"
  | "liquidation_cascade"
  | "mega_trade"
  | "onchain_transfer"
  | "positioning_shift"
  | "wall_eaten"
  | "wall_pulled";
export type Market2 = "spot" | "usdm_futures";
export type Market3 = "spot" | "usdm_futures";

export interface EngineProtocol {
  Alert?: Alert;
  AnalysisSnapshotResponse?: AnalysisSnapshotResponse;
  AuditEntry?: AuditEntry;
  AutoTradeRequest?: AutoTradeRequest;
  BacktestJobInfo?: BacktestJobInfo;
  BacktestRequest?: BacktestRequest;
  CandlesResponse?: CandlesResponse;
  CheckInfo?: CheckInfo;
  ConnectionInfo?: ConnectionInfo;
  CostInfo?: CostInfo;
  DecisionInfo?: DecisionInfo;
  EngineEvent?: EngineEvent;
  EngineState?: EngineState;
  EngineStateChanged?: EngineStateChanged;
  ErrorResponse?: ErrorResponse;
  ExecutionCloseRequest?: ExecutionCloseRequest;
  ExecutionOrderInfo?: ExecutionOrderInfo;
  ExecutionPositionInfo?: ExecutionPositionInfo;
  ExecutionTradeResponse?: ExecutionTradeResponse;
  FocusRequest?: FocusRequest;
  FocusResponse?: FocusResponse;
  ForwardStatInfo?: ForwardStatInfo;
  HealthResponse?: HealthResponse;
  Heartbeat?: Heartbeat;
  HistoryCoverageInfo?: HistoryCoverageInfo;
  HistoryJobInfo?: HistoryJobInfo;
  HistoryStatusResponse?: HistoryStatusResponse;
  HistorySyncReportInfo?: HistorySyncReportInfo;
  HistorySyncRequest?: HistorySyncRequest;
  ImpactInfo?: ImpactInfo;
  KillSwitchEngageRequest?: KillSwitchEngageRequest;
  KillSwitchEngaged?: KillSwitchEngaged;
  KillSwitchInfo?: KillSwitchInfo;
  KillSwitchReleaseRequest?: KillSwitchReleaseRequest;
  KillSwitchReleased?: KillSwitchReleased;
  KillSwitchResponse?: KillSwitchResponse;
  LevelInfo?: LevelInfo;
  LevelsResponse?: LevelsResponse;
  LoopLagInfo?: LoopLagInfo;
  Market?: Market;
  MarketServiceInfo?: MarketServiceInfo;
  MarketSignal?: MarketSignal;
  MarketStatusResponse?: MarketStatusResponse;
  ModelInfo?: ModelInfo;
  OpportunityDetail?: OpportunityDetail;
  OpportunityScored?: OpportunityScored;
  OpportunityStatsResponse?: OpportunityStatsResponse;
  OpportunitySummary?: OpportunitySummary;
  OrderBookInfo?: OrderBookInfo;
  OrderBookResynced?: OrderBookResynced;
  PaperAccountInfo?: PaperAccountInfo;
  PaperPositionInfo?: PaperPositionInfo;
  PaperTradeEvent?: PaperTradeEvent;
  PaperTradeInfo?: PaperTradeInfo;
  PositioningInfo?: PositioningInfo;
  PredictionResponse?: PredictionResponse;
  ReadinessChanged?: ReadinessChanged;
  ReadinessInfo?: ReadinessInfo;
  RestBudgetInfo?: RestBudgetInfo;
  RiskEventInfo?: RiskEventInfo;
  ScanRowInfo?: ScanRowInfo;
  ScannerStatsInfo?: ScannerStatsInfo;
  ScannerTopResponse?: ScannerTopResponse;
  ScoreComponentInfo?: ScoreComponentInfo;
  ScorePenaltyInfo?: ScorePenaltyInfo;
  ServiceHealthChanged?: ServiceHealthChanged;
  Severity?: Severity;
  ShutdownResponse?: ShutdownResponse;
  SignalInfo?: SignalInfo;
  SignalKind?: SignalKind;
  SimilarMatchInfo?: SimilarMatchInfo;
  SimilarResponse?: SimilarResponse;
  StatusResponse?: StatusResponse;
  StrategyInfo?: StrategyInfo;
  StrategyRegistryInfo?: StrategyRegistryInfo;
  StreamConnectionChanged?: StreamConnectionChanged;
  SymbolDelisted?: SymbolDelisted;
  SymbolListed?: SymbolListed;
  TakeProfitInput?: TakeProfitInput;
  TaskInfo?: TaskInfo;
  TestnetKeyRequest?: TestnetKeyRequest;
  TestnetKeyResponse?: TestnetKeyResponse;
  TestnetTradeRequest?: TestnetTradeRequest;
  TickerInfo?: TickerInfo;
  TickersResponse?: TickersResponse;
  TradeGapInfo?: TradeGapInfo;
  TradingMode?: TradingMode;
  TradingModeChanged?: TradingModeChanged;
  TradingModeRequest?: TradingModeRequest;
  TradingModeResponse?: TradingModeResponse;
  TrainJobInfo?: TrainJobInfo;
  TrainRequest?: TrainRequest;
  TrendBreakInfo?: TrendBreakInfo;
  TrendLineInfo?: TrendLineInfo;
  TrendResponse?: TrendResponse;
  WhaleAlert?: WhaleAlert;
  WhaleAlertInfo?: WhaleAlertInfo;
  WhaleAlertKind?: WhaleAlertKind;
  WhaleStatsInfo?: WhaleStatsInfo;
  WhaleSummaryResponse?: WhaleSummaryResponse;
  WhaleSymbolSummary?: WhaleSymbolSummary;
  WhaleTradeInfo?: WhaleTradeInfo;
  WsAuthMessage?: WsAuthMessage;
  WsAuthOk?: WsAuthOk;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "Alert".
 */
export interface Alert {
  context?: {};
  message: string;
  severity: Severity;
  title: string;
  ts_ms?: number;
  type: "Alert";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "AnalysisSnapshotResponse".
 */
export interface AnalysisSnapshotResponse {
  bar_open_time_ms: number;
  features: {
    [k: string]: number | null;
  };
  indicators: {
    [k: string]: unknown;
  };
  interval: string;
  market: Market;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "AuditEntry".
 */
export interface AuditEntry {
  action: string;
  actor: string;
  details: {
    [k: string]: unknown;
  };
  id: number;
  ts: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "AutoTradeRequest".
 */
export interface AutoTradeRequest {
  enabled: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "BacktestJobInfo".
 */
export interface BacktestJobInfo {
  error: string | null;
  finished_ms: number | null;
  id: number;
  interval: string;
  market: string;
  report_name: string | null;
  since_ms: number | null;
  stage: string;
  started_ms: number;
  state: string;
  symbols: string[];
  walk_forward: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "BacktestRequest".
 */
export interface BacktestRequest {
  interval?: string;
  leverage?: number;
  market?: Market1;
  max_hold_bars?: number;
  max_positions?: number;
  risk_per_trade?: number;
  since_ms?: number | null;
  /**
   * @minItems 1
   * @maxItems 20
   */
  symbols:
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ];
  walk_forward?: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "CandlesResponse".
 */
export interface CandlesResponse {
  columns: string[];
  interval: string;
  market: Market;
  rows: number[][];
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "CheckInfo".
 */
export interface CheckInfo {
  message: string;
  name: string;
  passed: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ConnectionInfo".
 */
export interface ConnectionInfo {
  connected: boolean;
  connected_for_s: number | null;
  healthy: boolean;
  last_error: string | null;
  last_message_age_s: number | null;
  messages: number;
  name: string;
  reconnects: number;
  route: string;
  streams: number;
  subscribed: number;
  url: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "CostInfo".
 */
export interface CostInfo {
  estimated: boolean;
  fee_pct: number;
  funding_pct: number;
  notes: string[];
  slippage_pct: number;
  spread_pct: number;
  total_pct: number;
}
/**
 * Karar günlüğü: işlem neden açıldı / neden açılmadı.
 *
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "DecisionInfo".
 */
export interface DecisionInfo {
  created_ms: number;
  direction: string;
  id: string;
  market: string;
  mode: string;
  opportunity_score?: number | null;
  outcome?: string | null;
  reason?: string | null;
  risk_metrics: {
    [k: string]: unknown;
  };
  risk_reasons: {
    [k: string]: unknown;
  }[];
  risk_verdict: "approved" | "rejected" | "pending";
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "EngineStateChanged".
 */
export interface EngineStateChanged {
  current: EngineState;
  previous: EngineState;
  reason: string;
  ts_ms?: number;
  type: "EngineStateChanged";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TradingModeChanged".
 */
export interface TradingModeChanged {
  actor: string;
  current: TradingMode;
  previous: TradingMode;
  ts_ms?: number;
  type: "TradingModeChanged";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "KillSwitchEngaged".
 */
export interface KillSwitchEngaged {
  actor: string;
  reason: string;
  ts_ms?: number;
  type: "KillSwitchEngaged";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "KillSwitchReleased".
 */
export interface KillSwitchReleased {
  actor: string;
  ts_ms?: number;
  type: "KillSwitchReleased";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ReadinessChanged".
 */
export interface ReadinessChanged {
  condition: string;
  detail?: string;
  ready: boolean;
  ts_ms?: number;
  type: "ReadinessChanged";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ServiceHealthChanged".
 */
export interface ServiceHealthChanged {
  detail?: string;
  healthy: boolean;
  service: string;
  ts_ms?: number;
  type: "ServiceHealthChanged";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "Heartbeat".
 */
export interface Heartbeat {
  loop_lag_ms: number;
  state: EngineState;
  trading_mode: TradingMode;
  ts_ms?: number;
  type: "Heartbeat";
  uptime_s: number;
}
/**
 * Daha önce görülmemiş bir sembol işlem görmeye başladı (yeni listeleme).
 *
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "SymbolListed".
 */
export interface SymbolListed {
  market: Market;
  onboard_date_ms?: number | null;
  symbol: string;
  ts_ms?: number;
  type: "SymbolListed";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "SymbolDelisted".
 */
export interface SymbolDelisted {
  market: Market;
  status: string;
  symbol: string;
  ts_ms?: number;
  type: "SymbolDelisted";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "StreamConnectionChanged".
 */
export interface StreamConnectionChanged {
  connected: boolean;
  connection: string;
  market: Market;
  reason?: string;
  streams: number;
  ts_ms?: number;
  type: "StreamConnectionChanged";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "OrderBookResynced".
 */
export interface OrderBookResynced {
  market: Market;
  reason: string;
  symbol: string;
  ts_ms?: number;
  type: "OrderBookResynced";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "MarketSignal".
 */
export interface MarketSignal {
  details?: {};
  kind: SignalKind;
  market: Market;
  message: string;
  severity: Severity;
  symbol: string;
  threshold: number;
  ts_ms?: number;
  type: "MarketSignal";
  value: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WhaleAlert".
 */
export interface WhaleAlert {
  details?: {};
  kind: WhaleAlertKind;
  market: Market | null;
  message: string;
  notional: number;
  severity: Severity;
  side: string;
  symbol: string;
  ts_ms?: number;
  type: "WhaleAlert";
}
/**
 * Eşik üstü fırsat puanı (arayüz bildirimi; emir değildir).
 *
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "OpportunityScored".
 */
export interface OpportunityScored {
  bar_open_time_ms: number;
  cost_pct: number;
  direction: string;
  historical_hit_rate?: number | null;
  historical_net_return_pct?: number | null;
  interval: string;
  market: Market;
  price: number;
  reasons: string[];
  reward_risk: number | null;
  score: number;
  stop_price: number | null;
  symbol: string;
  target_price: number | null;
  ts_ms?: number;
  type: "OpportunityScored";
}
/**
 * Yarışmada sanal pozisyon açıldı/kapandı (gerçek emir değildir).
 *
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "PaperTradeEvent".
 */
export interface PaperTradeEvent {
  action: string;
  direction: string;
  exit_reason?: string | null;
  market: Market;
  net_pnl?: number | null;
  price: number;
  qty: number;
  reason?: string;
  strategy: string;
  symbol: string;
  ts_ms?: number;
  type: "PaperTradeEvent";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ErrorResponse".
 */
export interface ErrorResponse {
  detail: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ExecutionCloseRequest".
 */
export interface ExecutionCloseRequest {
  market: Market;
  reason?: string;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ExecutionOrderInfo".
 */
export interface ExecutionOrderInfo {
  avg_price?: number | string | null;
  client_id: string;
  executed_qty: number | string;
  last_error?: string | null;
  market: string;
  price?: number | string | null;
  purpose: string;
  quantity?: number | string | null;
  side: string;
  status: string;
  symbol: string;
  trigger_price?: number | string | null;
  type: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ExecutionPositionInfo".
 */
export interface ExecutionPositionInfo {
  decision_id?: string | null;
  entry_price: number | string;
  fees: number | string;
  funding: number | string;
  market: string;
  protected: boolean;
  quantity: number | string;
  realized_pnl: number | string;
  state: string;
  symbol: string;
  take_profits_filled: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ExecutionTradeResponse".
 */
export interface ExecutionTradeResponse {
  decision_id: string;
  error?: string | null;
  filled_qty: number | string;
  protection_orders: number;
  state: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "FocusRequest".
 */
export interface FocusRequest {
  market: Market;
  /**
   * @maxItems 100
   */
  symbols: string[];
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "FocusResponse".
 */
export interface FocusResponse {
  focus: string[];
  market: Market;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ForwardStatInfo".
 */
export interface ForwardStatInfo {
  horizon_bars: number;
  mean_pct: number;
  median_pct: number;
  n: number;
  positive_rate: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "HealthResponse".
 */
export interface HealthResponse {
  status?: "ok";
  version: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "HistoryCoverageInfo".
 */
export interface HistoryCoverageInfo {
  interval: string;
  market: string;
  rows: number;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "HistoryJobInfo".
 */
export interface HistoryJobInfo {
  current: string | null;
  error: string | null;
  finished_ms: number | null;
  id: number;
  interval: string;
  market: Market;
  reports: HistorySyncReportInfo[];
  started_ms: number;
  state: string;
  symbols: string[];
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "HistorySyncReportInfo".
 */
export interface HistorySyncReportInfo {
  files_downloaded: number;
  files_skipped: number;
  first_open_ms: number | null;
  last_open_ms: number | null;
  rows_inserted: number;
  seconds: number;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "HistoryStatusResponse".
 */
export interface HistoryStatusResponse {
  coverage: HistoryCoverageInfo[];
  jobs: HistoryJobInfo[];
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "HistorySyncRequest".
 */
export interface HistorySyncRequest {
  interval?: string;
  market?: Market2;
  /**
   * @minItems 1
   * @maxItems 200
   */
  symbols: [string, ...string[]];
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ImpactInfo".
 */
export interface ImpactInfo {
  expected_direction: string;
  hit_rate: number;
  horizon_s: number;
  kind: string;
  mean_directional_pct: number;
  samples: number;
  std_pct: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "KillSwitchEngageRequest".
 */
export interface KillSwitchEngageRequest {
  reason: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "KillSwitchInfo".
 */
export interface KillSwitchInfo {
  actor?: string | null;
  engaged: boolean;
  reason?: string | null;
  since_ms?: number | null;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "KillSwitchReleaseRequest".
 */
export interface KillSwitchReleaseRequest {
  confirmation: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "KillSwitchResponse".
 */
export interface KillSwitchResponse {
  changed: boolean;
  engine_state: EngineState;
  kill_switch: KillSwitchInfo;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "LevelInfo".
 */
export interface LevelInfo {
  distance_pct: number;
  first_time_ms: number;
  kind: string;
  last_time_ms: number;
  price: number;
  strength: number;
  touches: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "LevelsResponse".
 */
export interface LevelsResponse {
  bars: number;
  interval: string;
  last_close: number | null;
  levels: LevelInfo[];
  market: Market;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "LoopLagInfo".
 */
export interface LoopLagInfo {
  last_ms: number;
  max_ms: number;
  p99_ms: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "MarketServiceInfo".
 */
export interface MarketServiceInfo {
  connections: ConnectionInfo[];
  focus: string[];
  last_discovery_error: string | null;
  market: Market;
  message_rates_per_s: {
    [k: string]: number;
  };
  order_books: OrderBookInfo[];
  ready: boolean;
  rest_budget: RestBudgetInfo;
  streams: number;
  tracked_symbols: number;
  trade_gaps: TradeGapInfo;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "OrderBookInfo".
 */
export interface OrderBookInfo {
  applied: number;
  best_ask: number | null;
  best_bid: number | null;
  imbalance_10: number | null;
  resyncs: number;
  state: string;
  symbol: string;
  update_id: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "RestBudgetInfo".
 */
export interface RestBudgetInfo {
  banned: boolean;
  blocked_for_s: number;
  limit_per_minute: number;
  total_used: number;
  used: number;
  waits: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TradeGapInfo".
 */
export interface TradeGapInfo {
  detected: number;
  duplicates: number;
  pending: number;
  recovered_trades: number;
  unrecovered_gaps: number;
  unrecovered_trades: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "MarketStatusResponse".
 */
export interface MarketStatusResponse {
  enabled: boolean;
  markets: MarketServiceInfo[];
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ModelInfo".
 */
export interface ModelInfo {
  calibration: {
    [k: string]: unknown;
  }[];
  cost: number;
  created_ms: number;
  disclaimer: string;
  feature_names: string[];
  horizon: number;
  id: string;
  interval: string;
  market: string;
  onnx_sha256: string;
  oos: {
    [k: string]: unknown;
  };
  parity_max_abs_diff: number;
  rows: number;
  side: string;
  symbols: string[];
  threshold: number;
  top_features: {
    [k: string]: number;
  };
  train_end_ms: number;
  train_start_ms: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "OpportunityDetail".
 */
export interface OpportunityDetail {
  bar_open_time_ms: number;
  calibration: {
    [k: string]: unknown;
  } | null;
  components: ScoreComponentInfo[];
  cost: CostInfo;
  direction: string;
  disclaimer: string;
  interval: string;
  market: Market;
  notes: string[];
  penalties: ScorePenaltyInfo[];
  price: number;
  raw_score: number;
  reward_risk: number | null;
  score: number;
  signals: {
    [k: string]: unknown;
  }[];
  source: "live" | "history";
  stop_price: number | null;
  symbol: string;
  target_pct: number | null;
  target_price: number | null;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ScoreComponentInfo".
 */
export interface ScoreComponentInfo {
  available: boolean;
  detail: string;
  key: string;
  points: number;
  signal: number;
  title: string;
  weight: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ScorePenaltyInfo".
 */
export interface ScorePenaltyInfo {
  detail: string;
  key: string;
  points: number;
  title: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "OpportunityStatsResponse".
 */
export interface OpportunityStatsResponse {
  bars: number;
  batch_ms_max: number;
  calibration_loaded: {
    [k: string]: boolean;
  };
  horizon_bars: number;
  incomplete_bars: number;
  interval: string;
  models_loaded: {
    [k: string]: string[];
  };
  publish_min_score: number;
  published: number;
  repair_failed: number;
  repaired_bars: number;
  scored: number;
  symbols: number;
  warmup_symbols: {
    [k: string]: number;
  };
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "OpportunitySummary".
 */
export interface OpportunitySummary {
  bar_open_time_ms: number;
  cost_pct: number;
  direction: string;
  historical_hit_rate: number | null;
  historical_net_return_pct: number | null;
  interval: string;
  market: Market;
  price: number;
  reasons: string[];
  reward_risk: number | null;
  score: number;
  stop_price: number | null;
  symbol: string;
  target_price: number | null;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "PaperAccountInfo".
 */
export interface PaperAccountInfo {
  days: number;
  equity: number;
  fees: number | null;
  funding: number | null;
  market: string;
  max_drawdown_pct: number | null;
  net_pnl: number | null;
  open_positions: number;
  profit_factor: number | null;
  sharpe: number | null;
  stage: string | null;
  strategy: string;
  total_return_pct: number | null;
  trades: number;
  win_rate: number | null;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "PaperPositionInfo".
 */
export interface PaperPositionInfo {
  bars_held: number;
  direction: string;
  entry_price: number;
  entry_time_ms: number;
  fees: number;
  funding: number;
  last_price: number;
  market: string;
  qty: number;
  reason: string;
  stop: number;
  strategy: string;
  symbol: string;
  target: number;
  unrealized_pnl: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "PaperTradeInfo".
 */
export interface PaperTradeInfo {
  direction: string;
  entry_price: number;
  entry_time_ms: number;
  exit_price: number | null;
  exit_reason: string | null;
  exit_time_ms: number | null;
  fees: number;
  funding: number;
  market: string;
  net_pnl: number;
  qty: number;
  r_multiple: number;
  reason: string;
  strategy: string;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "PositioningInfo".
 */
export interface PositioningInfo {
  divergence: boolean;
  global_long_change_pts: number;
  global_long_pct: number;
  global_ratio: number;
  open_interest_change_pct: number;
  open_interest_usd: number;
  symbol: string;
  timestamp_ms: number;
  top_long_change_pts: number;
  top_long_pct: number;
  top_ratio: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "PredictionResponse".
 */
export interface PredictionResponse {
  bar_open_time_ms: number;
  base_rate: number | null;
  disclaimer: string;
  horizon_bars: number;
  interval: string;
  missing_features: string[];
  model_id: string;
  oos_auc: number | null;
  probability: number;
  side: string;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ReadinessInfo".
 */
export interface ReadinessInfo {
  detail: string;
  name: string;
  ready: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "RiskEventInfo".
 */
export interface RiskEventInfo {
  action: string;
  details: {
    [k: string]: unknown;
  };
  id: number;
  market?: string | null;
  rule: string;
  severity: "info" | "warning" | "critical";
  symbol?: string | null;
  ts_ms: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ScanRowInfo".
 */
export interface ScanRowInfo {
  baseline_minutes: number;
  book_imbalance_10: number | null;
  book_notional_10: number | null;
  buy_quote_300s: number;
  change_15m_pct: number | null;
  change_1m_pct: number | null;
  change_24h_pct: number | null;
  change_5m_pct: number | null;
  imbalance_300s: number | null;
  imbalance_60s: number | null;
  last_price: number | null;
  listed_at_ms: number | null;
  market: Market;
  price_z_60s: number | null;
  quote_volume_24h: number | null;
  quote_volume_60s: number;
  sell_quote_300s: number;
  signals: string[];
  spread_bps: number | null;
  symbol: string;
  updated_ms: number;
  volatility_1m_pct: number | null;
  volume_z_60s: number | null;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ScannerStatsInfo".
 */
export interface ScannerStatsInfo {
  signals: number;
  symbols: number;
  tick_ms_last: number;
  tick_ms_max: number;
  ticks: number;
  warmup_done: {
    [k: string]: number;
  };
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ScannerTopResponse".
 */
export interface ScannerTopResponse {
  count: number;
  market: Market;
  rows: ScanRowInfo[];
  sort: string;
  stats: ScannerStatsInfo;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "ShutdownResponse".
 */
export interface ShutdownResponse {
  accepted?: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "SignalInfo".
 */
export interface SignalInfo {
  details: {
    [k: string]: unknown;
  };
  kind: string;
  market: Market;
  message: string;
  severity: string;
  symbol: string;
  threshold: number;
  ts_ms: number;
  value: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "SimilarMatchInfo".
 */
export interface SimilarMatchInfo {
  distance: number;
  end_time_ms: number;
  forward_pct: {
    [k: string]: number;
  };
  start_time_ms: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "SimilarResponse".
 */
export interface SimilarResponse {
  candidates: number;
  disclaimer?: string;
  forward: ForwardStatInfo[];
  interval: string;
  market: Market;
  matches: SimilarMatchInfo[];
  query_end_time_ms: number;
  symbol: string;
  window: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "StatusResponse".
 */
export interface StatusResponse {
  can_manage_positions: boolean;
  can_open_positions: boolean;
  engine_state: EngineState;
  kill_switch: KillSwitchInfo;
  loop_lag: LoopLagInfo;
  readiness: ReadinessInfo[];
  state_reason: string;
  tasks: TaskInfo[];
  trading_mode: TradingMode;
  uptime_s: number;
  version: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TaskInfo".
 */
export interface TaskInfo {
  last_error?: string | null;
  name: string;
  restarts: number;
  state: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "StrategyInfo".
 */
export interface StrategyInfo {
  category: string;
  description: string;
  markets: string[];
  name: string;
  title: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "StrategyRegistryInfo".
 */
export interface StrategyRegistryInfo {
  category: string;
  id: string;
  live_approved: boolean;
  metrics: {
    [k: string]: {
      [k: string]: unknown;
    };
  };
  name: string;
  stage: string;
  stage_changed_at: number;
  title: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TakeProfitInput".
 */
export interface TakeProfitInput {
  fraction: number | string;
  price: number | string;
}
/**
 * Binance TEST AĞI anahtarı. Gerçek hesap anahtarı bu sürümde kabul edilmez (G1 onayı).
 *
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TestnetKeyRequest".
 */
export interface TestnetKeyRequest {
  api_key: string;
  market: Market;
  secret: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TestnetKeyResponse".
 */
export interface TestnetKeyResponse {
  can_trade?: boolean | null;
  key_hint?: string | null;
  message: string;
  stored: boolean;
  verified: boolean;
}
/**
 * Test ağında elle işlem açma. Zarar durdur (veya iz süren stop) zorunludur.
 *
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TestnetTradeRequest".
 */
export interface TestnetTradeRequest {
  breakeven_after_first_tp?: boolean;
  direction: "long" | "short";
  leverage?: number | null;
  limit_price?: number | string | null;
  market: Market;
  quantity: number | string;
  reason?: string;
  reference_price: number | string;
  stop_loss?: number | string | null;
  symbol: string;
  /**
   * @maxItems 5
   */
  take_profits?:
    | []
    | [TakeProfitInput]
    | [TakeProfitInput, TakeProfitInput]
    | [TakeProfitInput, TakeProfitInput, TakeProfitInput]
    | [TakeProfitInput, TakeProfitInput, TakeProfitInput, TakeProfitInput]
    | [TakeProfitInput, TakeProfitInput, TakeProfitInput, TakeProfitInput, TakeProfitInput];
  trailing_activation?: number | string | null;
  trailing_callback_pct?: number | string | null;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TickerInfo".
 */
export interface TickerInfo {
  change_pct: number;
  event_time_ms: number;
  funding_rate?: number | null;
  high: number;
  last: number;
  low: number;
  mark_price?: number | null;
  quote_volume: number;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TickersResponse".
 */
export interface TickersResponse {
  count: number;
  market: Market;
  tickers: TickerInfo[];
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TradingModeRequest".
 */
export interface TradingModeRequest {
  acknowledgement?: string | null;
  mode: TradingMode;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TradingModeResponse".
 */
export interface TradingModeResponse {
  accepted: boolean;
  checks: CheckInfo[];
  mode: TradingMode;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TrainJobInfo".
 */
export interface TrainJobInfo {
  error: string | null;
  finished_ms: number | null;
  horizon: number;
  id: number;
  interval: string;
  market: Market;
  model_id: string | null;
  oos: {
    [k: string]: unknown;
  };
  side: string;
  stage: string;
  started_ms: number;
  state: string;
  symbols: string[];
  with_futures: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TrainRequest".
 */
export interface TrainRequest {
  cost?: number | null;
  horizon?: number;
  interval?: string;
  market?: Market3;
  side?: "long" | "short";
  since_ms?: number | null;
  /**
   * @minItems 1
   * @maxItems 50
   */
  symbols: [string, ...string[]];
  with_futures?: boolean;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TrendBreakInfo".
 */
export interface TrendBreakInfo {
  close: number;
  direction: string;
  line_kind: string;
  line_value: number;
  penetration_atr: number;
  time_ms: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TrendLineInfo".
 */
export interface TrendLineInfo {
  a_price: number;
  a_time_ms: number;
  b_price: number;
  b_time_ms: number;
  kind: string;
  slope_per_bar: number;
  value_now: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "TrendResponse".
 */
export interface TrendResponse {
  active: TrendLineInfo[];
  bars: number;
  breaks: TrendBreakInfo[];
  interval: string;
  market: Market;
  symbol: string;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WhaleAlertInfo".
 */
export interface WhaleAlertInfo {
  details: {
    [k: string]: unknown;
  };
  kind: string;
  market: Market | null;
  message: string;
  notional: number;
  severity: string;
  side: string;
  symbol: string;
  ts_ms: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WhaleStatsInfo".
 */
export interface WhaleStatsInfo {
  alerts: number;
  impact_pending: number;
  liquidations_5m: {
    [k: string]: number;
  };
  onchain_enabled: boolean;
  orders_seen: number;
  positioning_symbols: number;
  tick_ms_max: number;
  ticks: number;
  whale_trades: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WhaleSummaryResponse".
 */
export interface WhaleSummaryResponse {
  market: Market;
  rows: WhaleSymbolSummary[];
  stats: WhaleStatsInfo;
  window_s: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WhaleSymbolSummary".
 */
export interface WhaleSymbolSummary {
  buy_usd: number;
  count: number;
  largest_usd: number;
  last_ms: number;
  net_usd: number;
  sell_usd: number;
  symbol: string;
  threshold_usd: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WhaleTradeInfo".
 */
export interface WhaleTradeInfo {
  avg_price: number;
  fills: number;
  market: Market;
  notional: number;
  qty: number;
  side: string;
  sweep_pct: number;
  symbol: string;
  threshold: number;
  time_ms: number;
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WsAuthMessage".
 */
export interface WsAuthMessage {
  token: string;
  type: "auth";
}
/**
 * This interface was referenced by `EngineProtocol`'s JSON-Schema
 * via the `definition` "WsAuthOk".
 */
export interface WsAuthOk {
  type?: "auth_ok";
  version: string;
}

export const PROTOCOL_VERSION = 1;
