-- Aşama 13: uzaktan kontrol. Eşleştirilmiş telefonlar ve uzaktan gelen her komut denemesi.
-- last_seq kalıcıdır: motor yeniden başlasa da eski bir komut tekrar oynatılamaz.
CREATE TABLE remote_devices (
    id            TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    signing_key   TEXT    NOT NULL,
    guarded_key   TEXT    NOT NULL,
    protection    TEXT    NOT NULL CHECK (protection IN ('secure_enclave', 'software')),
    paired_at     INTEGER NOT NULL,
    last_seq      INTEGER NOT NULL DEFAULT 0,
    last_seen     INTEGER,
    revoked_at    INTEGER
) STRICT;

CREATE TABLE remote_commands (
    id          INTEGER PRIMARY KEY,
    ts          INTEGER NOT NULL,
    device_id   TEXT,
    seq         INTEGER,
    command     TEXT,
    accepted    INTEGER NOT NULL CHECK (accepted IN (0, 1)),
    reason      TEXT,
    result      TEXT
) STRICT;
CREATE INDEX ix_remote_commands_ts ON remote_commands (ts);
