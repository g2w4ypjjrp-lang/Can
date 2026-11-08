-- Aşama 15: lisans durumu (tek satır). İmzalı kira gizli değildir (bu bilgisayara bağlıdır);
-- cihaz anahtarı şifreli kasada (secrets: license.device_key) tutulur. Lisans anahtarının
-- kendisi saklanmaz, yalnızca ipucu (ATI-****-****-****-XXXX).
CREATE TABLE license_state (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    lease_json        TEXT,
    key_hint          TEXT,
    server_offset_ms  INTEGER NOT NULL DEFAULT 0,
    max_seen_ms       INTEGER NOT NULL DEFAULT 0,
    last_renewed_ms   INTEGER,
    last_error        TEXT,
    revoked_code      TEXT,
    revoked_message   TEXT,
    updated_at        INTEGER NOT NULL
);
