-- Telefon tarayıcısına bildirim (Web Push) abonelikleri: eşleştirilmiş cihaz başına bir tane.
-- Bildirim içeriği motorda tarayıcının anahtarına şifrelenir; burada yalnızca bildirim servisinin
-- adresi ve tarayıcının açık anahtarları durur. Cihazın eşleştirmesi kaldırılınca silinir.
CREATE TABLE remote_push (
    device_id   TEXT    PRIMARY KEY,
    endpoint    TEXT    NOT NULL,
    p256dh      TEXT    NOT NULL,
    auth        TEXT    NOT NULL,
    created_at  INTEGER NOT NULL,
    last_ok_at  INTEGER,
    last_error  TEXT,
    failures    INTEGER NOT NULL DEFAULT 0
) STRICT;
