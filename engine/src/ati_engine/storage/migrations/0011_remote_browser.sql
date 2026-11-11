-- Telefon tarayıcısı (QR → canarslan.net.tr/telefon) da eşleşebilir: koruma türü "browser".
-- SQLite CHECK kısıtını değiştiremediği için tablo aynı sütunlarla yeniden kurulur. Tarayıcı
-- cihazı biyometrik kanıt veremez; korumalı komutları motor reddeder (browser_view_only).
CREATE TABLE remote_devices_new (
    id            TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    signing_key   TEXT    NOT NULL,
    guarded_key   TEXT    NOT NULL,
    protection    TEXT    NOT NULL CHECK (protection IN ('secure_enclave', 'software', 'browser')),
    paired_at     INTEGER NOT NULL,
    last_seq      INTEGER NOT NULL DEFAULT 0,
    last_seen     INTEGER,
    revoked_at    INTEGER,
    kx_key        TEXT
) STRICT;
INSERT INTO remote_devices_new (id, name, signing_key, guarded_key, protection, paired_at,
                                last_seq, last_seen, revoked_at, kx_key)
    SELECT id, name, signing_key, guarded_key, protection, paired_at, last_seq, last_seen,
           revoked_at, kx_key
    FROM remote_devices;
DROP TABLE remote_devices;
ALTER TABLE remote_devices_new RENAME TO remote_devices;
