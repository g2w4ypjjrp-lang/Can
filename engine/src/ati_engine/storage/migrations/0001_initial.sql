-- AI Trading Intelligence - yerel motor veritabanı, ilk şema.
--
-- Kurallar:
--   * Zaman damgaları: Unix epoch milisaniye (INTEGER).
--   * Fiyat/miktar/tutar: Decimal hassasiyetini korumak için TEXT ("76098.01").
--   * JSON alanları: TEXT, json_valid() ile doğrulanır.
--   * Tablolar STRICT: tür uyuşmazlığında SQLite hata verir.
--   * mode sütunu: 'paper' | 'testnet' | 'live'. Sanal ve gerçek kayıtlar asla karışmaz.

-- Anahtar/değer ayarları ve kalıcı motor durumu (ör. acil durdurma).
CREATE TABLE settings (
    key         TEXT    PRIMARY KEY,
    value       TEXT    NOT NULL CHECK (json_valid(value)),
    updated_at  INTEGER NOT NULL
) STRICT;

-- Şifrelenmiş gizli bilgiler (Binance API anahtarları, yerel API belirteci, lisans kirası).
CREATE TABLE secrets (
    name        TEXT    PRIMARY KEY,
    provider    TEXT    NOT NULL CHECK (provider IN ('dpapi', 'aesgcm')),
    ciphertext  BLOB    NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
) STRICT;

-- Borsa sembolleri ve kuralları (exchangeInfo). Yeni listelenen coin tespiti first_seen_at ile.
CREATE TABLE exchange_symbols (
    market          TEXT    NOT NULL CHECK (market IN ('spot', 'usdm_futures')),
    symbol          TEXT    NOT NULL,
    base_asset      TEXT    NOT NULL,
    quote_asset     TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    contract_type   TEXT,
    tick_size       TEXT    NOT NULL,
    step_size       TEXT    NOT NULL,
    min_qty         TEXT    NOT NULL,
    min_notional    TEXT    NOT NULL,
    filters         TEXT    NOT NULL CHECK (json_valid(filters)),
    onboard_date    INTEGER,
    first_seen_at   INTEGER NOT NULL,
    last_seen_at    INTEGER NOT NULL,
    delisted_at     INTEGER,
    PRIMARY KEY (market, symbol)
) STRICT;
CREATE INDEX ix_exchange_symbols_quote ON exchange_symbols (quote_asset, status);

-- Tarihsel veri senkron durumu: artımlı güncelleme için her seri nerede kaldı.
CREATE TABLE history_sync_state (
    market          TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    dataset         TEXT    NOT NULL,          -- 'klines_1m', 'klines_1h', 'agg_trades', ...
    first_ts        INTEGER,
    last_ts         INTEGER,
    source          TEXT    NOT NULL,          -- 'bulk_archive' | 'rest' | 'ws'
    updated_at      INTEGER NOT NULL,
    PRIMARY KEY (market, symbol, dataset)
) STRICT;

-- Strateji kayıt defteri ve terfi hattı. Bir strateji asla otomatik olarak 'live'a geçmez.
CREATE TABLE strategies (
    id              TEXT    PRIMARY KEY,       -- ör. 'momentum.v3'
    name            TEXT    NOT NULL,
    version         INTEGER NOT NULL,
    stage           TEXT    NOT NULL CHECK (stage IN (
                        'research', 'backtest', 'walk_forward', 'paper',
                        'live_candidate', 'live', 'retired')),
    params          TEXT    NOT NULL CHECK (json_valid(params)),
    weight          TEXT    NOT NULL DEFAULT '0',
    created_at      INTEGER NOT NULL,
    stage_changed_at INTEGER NOT NULL,
    approved_live_by TEXT,                      -- 'live' aşaması için kullanıcı onayı kaydı
    approved_live_at INTEGER,
    CHECK (stage <> 'live' OR (approved_live_by IS NOT NULL AND approved_live_at IS NOT NULL)),
    UNIQUE (name, version)
) STRICT;

-- Strateji performans ölçümleri (pencere bazlı).
CREATE TABLE strategy_metrics (
    strategy_id     TEXT    NOT NULL REFERENCES strategies (id),
    mode            TEXT    NOT NULL CHECK (mode IN ('backtest', 'walk_forward', 'paper', 'testnet', 'live')),
    window_start    INTEGER NOT NULL,
    window_end      INTEGER NOT NULL,
    trades          INTEGER NOT NULL,
    win_rate        REAL,
    profit_factor   REAL,
    sharpe          REAL,
    sortino         REAL,
    max_drawdown    REAL,
    net_pnl         TEXT,
    computed_at     INTEGER NOT NULL,
    PRIMARY KEY (strategy_id, mode, window_start, window_end)
) STRICT;

-- Karar günlüğü: "İşlem neden açıldı, hangi sinyaller, hangi strateji, neden kâr/zarar".
CREATE TABLE decisions (
    id              TEXT    PRIMARY KEY,       -- UUIDv7
    created_at      INTEGER NOT NULL,
    mode            TEXT    NOT NULL CHECK (mode IN ('paper', 'testnet', 'live')),
    market          TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL CHECK (direction IN ('long', 'short', 'flat')),
    strategy_id     TEXT    REFERENCES strategies (id),
    opportunity_score REAL  CHECK (opportunity_score BETWEEN 0 AND 100),
    confidence      REAL    CHECK (confidence BETWEEN 0 AND 1),
    signals         TEXT    NOT NULL CHECK (json_valid(signals)),
    features        TEXT    NOT NULL CHECK (json_valid(features)),
    risk_verdict    TEXT    NOT NULL CHECK (risk_verdict IN ('approved', 'rejected', 'pending')),
    risk_reasons    TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(risk_reasons)),
    outcome         TEXT    CHECK (outcome IN ('win', 'loss', 'breakeven', 'not_executed')),
    realized_pnl    TEXT,
    post_mortem     TEXT    CHECK (post_mortem IS NULL OR json_valid(post_mortem)),
    closed_at       INTEGER
) STRICT;
CREATE INDEX ix_decisions_symbol_time ON decisions (symbol, created_at);
CREATE INDEX ix_decisions_strategy ON decisions (strategy_id, created_at);

-- Emirler. id = clientOrderId (yerelde üretilir, idempotent yeniden deneme için).
CREATE TABLE orders (
    id                  TEXT    PRIMARY KEY,
    mode                TEXT    NOT NULL CHECK (mode IN ('paper', 'testnet', 'live')),
    market              TEXT    NOT NULL,
    symbol              TEXT    NOT NULL,
    side                TEXT    NOT NULL CHECK (side IN ('BUY', 'SELL')),
    position_side       TEXT    NOT NULL DEFAULT 'BOTH' CHECK (position_side IN ('LONG', 'SHORT', 'BOTH')),
    type                TEXT    NOT NULL,
    time_in_force       TEXT,
    quantity            TEXT    NOT NULL,
    price               TEXT,
    stop_price          TEXT,
    reduce_only         INTEGER NOT NULL DEFAULT 0 CHECK (reduce_only IN (0, 1)),
    status              TEXT    NOT NULL CHECK (status IN (
                            'PENDING_NEW', 'NEW', 'PARTIALLY_FILLED', 'FILLED',
                            'CANCELED', 'REJECTED', 'EXPIRED')),
    exchange_order_id   TEXT,
    filled_qty          TEXT    NOT NULL DEFAULT '0',
    avg_fill_price      TEXT,
    decision_id         TEXT    REFERENCES decisions (id),
    purpose             TEXT    NOT NULL CHECK (purpose IN (
                            'entry', 'scale_in', 'take_profit', 'stop_loss',
                            'trailing_stop', 'exit', 'emergency_close')),
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    last_error          TEXT
) STRICT;
CREATE INDEX ix_orders_open ON orders (mode, status) WHERE status IN ('PENDING_NEW', 'NEW', 'PARTIALLY_FILLED');
CREATE UNIQUE INDEX ux_orders_exchange_id ON orders (mode, market, exchange_order_id) WHERE exchange_order_id IS NOT NULL;

-- Gerçekleşmeler (fills). Borsadan gelen trade_id ile tekilleştirilir.
CREATE TABLE fills (
    id                  INTEGER PRIMARY KEY,
    order_id            TEXT    NOT NULL REFERENCES orders (id),
    mode                TEXT    NOT NULL,
    market              TEXT    NOT NULL,
    symbol              TEXT    NOT NULL,
    trade_id            TEXT    NOT NULL,
    price               TEXT    NOT NULL,
    quantity            TEXT    NOT NULL,
    commission          TEXT    NOT NULL,
    commission_asset    TEXT    NOT NULL,
    is_maker            INTEGER NOT NULL CHECK (is_maker IN (0, 1)),
    realized_pnl        TEXT,
    ts                  INTEGER NOT NULL,
    UNIQUE (mode, market, symbol, trade_id)
) STRICT;

-- Pozisyonlar (spot için de envanter pozisyonu olarak tutulur).
CREATE TABLE positions (
    id                  TEXT    PRIMARY KEY,
    mode                TEXT    NOT NULL CHECK (mode IN ('paper', 'testnet', 'live')),
    market              TEXT    NOT NULL,
    symbol              TEXT    NOT NULL,
    side                TEXT    NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    status              TEXT    NOT NULL CHECK (status IN ('open', 'closing', 'closed')),
    quantity            TEXT    NOT NULL,
    entry_price         TEXT    NOT NULL,
    leverage            INTEGER NOT NULL DEFAULT 1 CHECK (leverage >= 1),
    stop_loss           TEXT,
    take_profit         TEXT,
    liquidation_price   TEXT,
    realized_pnl        TEXT    NOT NULL DEFAULT '0',
    fees_paid           TEXT    NOT NULL DEFAULT '0',
    funding_paid        TEXT    NOT NULL DEFAULT '0',
    decision_id         TEXT    REFERENCES decisions (id),
    opened_at           INTEGER NOT NULL,
    closed_at           INTEGER,
    close_reason        TEXT
) STRICT;
CREATE UNIQUE INDEX ux_positions_one_open ON positions (mode, market, symbol, side) WHERE status <> 'closed';

-- Risk olayları (limit ihlali, ret, güvenli moda geçiş vb.).
CREATE TABLE risk_events (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    rule        TEXT    NOT NULL,
    severity    TEXT    NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    market      TEXT,
    symbol      TEXT,
    details     TEXT    NOT NULL CHECK (json_valid(details)),
    action      TEXT    NOT NULL
) STRICT;
CREATE INDEX ix_risk_events_ts ON risk_events (ts);

-- Balina olayları (Binance büyük işlemleri, emir defteri duvarları, zincir üstü transferler).
CREATE TABLE whale_events (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    source      TEXT    NOT NULL CHECK (source IN ('binance_trade', 'binance_orderbook', 'binance_liquidation', 'onchain')),
    market      TEXT,
    symbol      TEXT,
    side        TEXT    CHECK (side IN ('buy', 'sell', 'inflow', 'outflow', 'transfer')),
    notional_usd TEXT   NOT NULL,
    details     TEXT    NOT NULL CHECK (json_valid(details))
) STRICT;
CREATE INDEX ix_whale_events_symbol_ts ON whale_events (symbol, ts);

-- Kullanıcıya gösterilen uyarılar / bildirim merkezi.
CREATE TABLE alerts (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    category    TEXT    NOT NULL,
    severity    TEXT    NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    title       TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    read_at     INTEGER
) STRICT;

-- Değiştirilemez, hash zincirli yerel denetim kaydı.
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    actor       TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    details     TEXT    NOT NULL CHECK (json_valid(details)),
    prev_hash   TEXT    NOT NULL,
    hash        TEXT    NOT NULL UNIQUE
) STRICT;

CREATE TRIGGER trg_audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log kayıtları değiştirilemez');
END;

CREATE TRIGGER trg_audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log kayıtları silinemez');
END;
