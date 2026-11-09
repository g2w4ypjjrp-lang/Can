-- Aşama 16: yönetici girişi. Davet bağlantıları ve TOTP doğrulama adımı için tek kullanımlık
-- belirteçler (yalnızca SHA-256 özeti saklanır); aynı TOTP kodunun ikinci kez kullanılmasını
-- engellemek için son kullanılan zaman adımı.

ALTER TABLE admin_users ADD COLUMN totp_last_counter bigint;

CREATE TABLE admin_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id    uuid NOT NULL REFERENCES admin_users (id) ON DELETE CASCADE,
    purpose     text NOT NULL CHECK (purpose IN ('invite', 'totp_challenge')),
    token_hash  bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
    attempts    integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX ix_admin_tokens_admin ON admin_tokens (admin_id, purpose);
