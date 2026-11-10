-- Müşteri hesabında iki adımlı doğrulama (TOTP + tek kullanımlık kurtarma kodları).
--
-- Sır AES-256-GCM ile şifreli durur (ATI_ADMIN_SECRET_KEK; ilişkili veri müşteri kimliği). Aynı
-- zaman adımındaki kod ikinci kez kabul edilmez (mfa_last_counter). Parola doğrulandıktan sonra
-- oturum açılmaz; 5 dakikalık, en çok 5 denemelik bir "kod adımı" (customer_login_challenges)
-- başlar.

ALTER TABLE customers
    ADD COLUMN mfa_enabled_at timestamptz,
    ADD COLUMN mfa_last_counter bigint,
    ADD COLUMN mfa_pending_enc bytea,
    ADD COLUMN mfa_recovery_hashes bytea[] NOT NULL DEFAULT '{}';

ALTER TABLE customers ADD CONSTRAINT customers_mfa_consistency
    CHECK (mfa_enabled_at IS NULL OR mfa_totp_secret_enc IS NOT NULL);

CREATE TABLE customer_login_challenges (
    token_hash  bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    customer_id uuid NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    attempts    integer NOT NULL DEFAULT 0 CHECK (attempts >= 0)
);
CREATE INDEX ix_customer_login_challenges_customer ON customer_login_challenges (customer_id);
