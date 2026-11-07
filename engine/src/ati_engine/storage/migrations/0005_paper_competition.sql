-- Aşama 9: sanal işlem yarışması. Her strateji, her piyasa için ayrı sanal hesapla aynı canlı
-- veriyi değerlendirir. Bu tablolar gerçek emir/pozisyon tablolarından (orders, fills,
-- positions) bilerek ayrıdır: yarışma kayıtları hiçbir zaman gerçek işlemle karışmaz.

CREATE TABLE paper_accounts (
    strategy_id     TEXT    NOT NULL,
    market          TEXT    NOT NULL CHECK (market IN ('spot', 'usdm_futures')),
    started_at      INTEGER NOT NULL,
    initial_equity  REAL    NOT NULL CHECK (initial_equity > 0),
    realized_pnl    REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (strategy_id, market)
) STRICT;

CREATE TABLE paper_positions (
    strategy_id     TEXT    NOT NULL,
    market          TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       INTEGER NOT NULL CHECK (direction IN (-1, 1)),
    qty             REAL    NOT NULL CHECK (qty > 0),
    entry_price     REAL    NOT NULL,
    entry_time      INTEGER NOT NULL,
    stop            REAL    NOT NULL,
    target          REAL    NOT NULL,
    risk_amount     REAL    NOT NULL,
    fees            REAL    NOT NULL,
    funding         REAL    NOT NULL,
    bars_held       INTEGER NOT NULL,
    reason          TEXT    NOT NULL,
    PRIMARY KEY (strategy_id, market, symbol)
) STRICT;

CREATE TABLE paper_trades (
    id              INTEGER PRIMARY KEY,
    strategy_id     TEXT    NOT NULL,
    market          TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       INTEGER NOT NULL CHECK (direction IN (-1, 1)),
    qty             REAL    NOT NULL,
    entry_price     REAL    NOT NULL,
    entry_time      INTEGER NOT NULL,
    exit_price      REAL    NOT NULL,
    exit_time       INTEGER NOT NULL,
    exit_reason     TEXT    NOT NULL,
    fees            REAL    NOT NULL,
    funding         REAL    NOT NULL,
    risk_amount     REAL    NOT NULL,
    net_pnl         REAL    NOT NULL,
    reason          TEXT    NOT NULL,
    fill_source     TEXT    NOT NULL
) STRICT;
CREATE INDEX ix_paper_trades_strategy ON paper_trades (strategy_id, market, exit_time);

-- Saatlik sermaye anlık görüntüleri (Sharpe, düşüş hesabı için).
CREATE TABLE paper_equity (
    strategy_id     TEXT    NOT NULL,
    market          TEXT    NOT NULL,
    ts              INTEGER NOT NULL,
    equity          REAL    NOT NULL,
    PRIMARY KEY (strategy_id, market, ts)
) STRICT;
