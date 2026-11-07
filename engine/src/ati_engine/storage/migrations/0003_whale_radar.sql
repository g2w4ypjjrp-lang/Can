-- Aşama 4: balina radarı uyarıları ve fiyat etkisi ölçümleri.
-- Büyük işlemler, duvarlar, tasfiyeler ve zincir üstü transferler 0001'deki whale_events
-- tablosuna yazılır; bu geçiş türetilmiş uyarıları ve etki ölçümlerini ekler.

CREATE TABLE whale_alerts (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    market      TEXT    CHECK (market IS NULL OR market IN ('spot', 'usdm_futures')),
    symbol      TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN (
                    'mega_trade', 'accumulation', 'distribution', 'wall_pulled', 'wall_eaten',
                    'liquidation_cascade', 'positioning_shift', 'onchain_transfer')),
    severity    TEXT    NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    side        TEXT    NOT NULL,
    notional    REAL    NOT NULL,
    message     TEXT    NOT NULL,
    details     TEXT    NOT NULL CHECK (json_valid(details))
) STRICT;
CREATE INDEX ix_whale_alerts_ts ON whale_alerts (ts);

-- Her balina olayının olaydan sonraki fiyat etkisi (yön beklentisine göre işaretli getiri).
CREATE TABLE whale_impacts (
    id              INTEGER PRIMARY KEY,
    event_ts        INTEGER NOT NULL,
    market          TEXT    NOT NULL CHECK (market IN ('spot', 'usdm_futures')),
    symbol          TEXT    NOT NULL,
    kind            TEXT    NOT NULL,
    direction       INTEGER NOT NULL CHECK (direction IN (-1, 1)),
    horizon_s       INTEGER NOT NULL CHECK (horizon_s > 0),
    return_pct      REAL    NOT NULL,
    directional_pct REAL    NOT NULL
) STRICT;
CREATE INDEX ix_whale_impacts_kind ON whale_impacts (kind, direction, horizon_s);
