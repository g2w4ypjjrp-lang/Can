-- Aşama 3: tarayıcı sinyalleri (hacim patlaması, ani fiyat hareketi, alıcı/satıcı dengesizliği,
-- likidite düşüşü, yeni listeleme). Öğrenen sistem (Aşama 10) bu kayıtları sonuçlarla eşleştirir.
CREATE TABLE market_signals (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    market      TEXT    NOT NULL CHECK (market IN ('spot', 'usdm_futures')),
    symbol      TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN (
                    'volume_spike', 'price_move', 'flow_imbalance', 'liquidity_drop', 'new_listing')),
    severity    TEXT    NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    value       REAL    NOT NULL,
    threshold   REAL    NOT NULL,
    message     TEXT    NOT NULL,
    details     TEXT    NOT NULL CHECK (json_valid(details))
) STRICT;
CREATE INDEX ix_market_signals_ts ON market_signals (ts);
CREATE INDEX ix_market_signals_symbol ON market_signals (market, symbol, ts);
