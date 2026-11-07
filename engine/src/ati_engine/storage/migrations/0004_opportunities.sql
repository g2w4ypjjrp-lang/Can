-- Aşama 7: yayınlanan fırsat puanları (eşik üstü). Puan tek başına emir üretmez; bu tablo
-- karar günlüğü (decisions) ve sonradan yapılacak değerlendirme için kayıt tutar.

CREATE TABLE opportunities (
    id           INTEGER PRIMARY KEY,
    ts           INTEGER NOT NULL,              -- mum açılış zamanı (ms)
    market       TEXT    NOT NULL CHECK (market IN ('spot', 'usdm_futures')),
    symbol       TEXT    NOT NULL,
    interval     TEXT    NOT NULL,
    direction    TEXT    NOT NULL CHECK (direction IN ('long', 'short')),
    score        REAL    NOT NULL CHECK (score BETWEEN 0 AND 100),
    price        REAL    NOT NULL,              -- analiz kaydı; para hesabı değildir
    stop_price   REAL,
    target_price REAL,
    reward_risk  REAL,
    cost_pct     REAL    NOT NULL,
    breakdown    TEXT    NOT NULL CHECK (json_valid(breakdown)),
    UNIQUE (market, symbol, interval, ts)
) STRICT;
CREATE INDEX ix_opportunities_ts ON opportunities (ts);
CREATE INDEX ix_opportunities_symbol ON opportunities (symbol, ts);
