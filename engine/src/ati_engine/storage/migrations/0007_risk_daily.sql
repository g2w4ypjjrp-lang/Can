-- Aşama 11: günlük risk muhasebesi (işlem modu başına, UTC günü).
-- Gün başı özsermaye ilk ölçümde yazılır ve motor yeniden başlatılsa da değişmez; böylece
-- yeniden başlatma günlük zarar sayacını sıfırlayamaz. Sınır aşılınca ``halted_at`` yazılır ve
-- o gün boyunca yeni işlem açılmaz (özsermaye toparlansa bile).
CREATE TABLE risk_daily (
    mode          TEXT    NOT NULL CHECK (mode IN ('paper', 'testnet', 'live')),
    day           TEXT    NOT NULL,
    start_equity  TEXT    NOT NULL,
    last_equity   TEXT    NOT NULL,
    min_equity    TEXT    NOT NULL,
    halted_at     INTEGER,
    halt_reason   TEXT,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (mode, day)
) STRICT;
