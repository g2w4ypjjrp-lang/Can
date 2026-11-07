-- AI Trading Intelligence - merkezi bulut veritabanı (PostgreSQL 16), ilk şema.
--
-- Bu veritabanı YALNIZCA şunları tutar: müşteri hesapları, yönetici hesapları, lisanslar,
-- cihaz aktivasyonları, siparişler/ödemeler, faturalar ve denetim kaydı.
-- Binance API anahtarları ve işlem verileri ASLA buluta gönderilmez; kullanıcının
-- bilgisayarında kalır.
--
-- Tutarlılık kuralları uygulama katmanına ek olarak veritabanında da zorlanır
-- (savunma derinliği): lisans durum geçişleri, cihaz limitleri, tek seferlik lisans
-- tahsisi, denetim kaydının değiştirilemezliği.

CREATE EXTENSION IF NOT EXISTS citext;

-- =====================================================================================
-- Tipler
-- =====================================================================================

CREATE TYPE customer_status AS ENUM ('active', 'blocked', 'deleted');
CREATE TYPE admin_status AS ENUM ('invited', 'active', 'blocked', 'deleted');
CREATE TYPE license_status AS ENUM (
    'generated',       -- Üretilmiş
    'ready_for_sale',  -- Satışa hazır
    'sold',            -- Satılmış
    'active',          -- Aktif
    'expired',         -- Süresi dolmuş
    'cancelled',       -- İptal edilmiş
    'frozen'           -- Dondurulmuş
);
CREATE TYPE device_platform AS ENUM ('windows', 'ios');
CREATE TYPE order_status AS ENUM (
    'pending', 'paid', 'fulfilled', 'failed', 'cancelled', 'refunded', 'partially_refunded'
);
CREATE TYPE payment_status AS ENUM (
    'pending', 'succeeded', 'failed', 'refunded', 'partially_refunded', 'disputed'
);
CREATE TYPE actor_type AS ENUM ('system', 'customer', 'admin', 'payment_webhook', 'engine');
CREATE TYPE token_purpose AS ENUM ('email_verification', 'password_reset', 'email_change');
CREATE TYPE outbox_status AS ENUM ('pending', 'sending', 'sent', 'failed');

CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;

-- İşlemi yapan aktör, uygulama tarafından işlem başında ayarlanır:
--   SET LOCAL ati.actor_type = 'admin'; SET LOCAL ati.actor_id = '<uuid>';
CREATE FUNCTION current_actor_type() RETURNS actor_type
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(NULLIF(current_setting('ati.actor_type', true), ''), 'system')::actor_type
$$;

CREATE FUNCTION current_actor_id() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('ati.actor_id', true), '')
$$;

-- =====================================================================================
-- Müşteriler
-- =====================================================================================

CREATE TABLE customers (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email               citext NOT NULL,
    email_verified_at   timestamptz,
    password_hash       text,                         -- Argon2id PHC dizgisi
    full_name           text,
    country_code        char(2) CHECK (country_code ~ '^[A-Z]{2}$'),
    locale              text NOT NULL DEFAULT 'tr',
    status              customer_status NOT NULL DEFAULT 'active',
    blocked_reason      text,
    blocked_at          timestamptz,
    mfa_totp_secret_enc bytea,                        -- isteğe bağlı müşteri 2FA (şifreli)
    marketing_consent   boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    last_login_at       timestamptz,
    deleted_at          timestamptz,
    CONSTRAINT customers_password_hash_argon2id
        CHECK (status = 'deleted' OR password_hash LIKE '$argon2id$%'),
    CONSTRAINT customers_blocked_consistency
        CHECK ((status = 'blocked') = (blocked_at IS NOT NULL)),
    CONSTRAINT customers_deleted_consistency
        CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
);
CREATE UNIQUE INDEX ux_customers_email_live ON customers (email) WHERE status <> 'deleted';
CREATE TRIGGER trg_customers_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- E-posta doğrulama / parola sıfırlama belirteçleri (yalnızca SHA-256 özetleri saklanır).
CREATE TABLE customer_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id uuid NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    purpose     token_purpose NOT NULL,
    token_hash  bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX ix_customer_tokens_customer ON customer_tokens (customer_id, purpose);

-- =====================================================================================
-- Cihazlar (Windows motoru ve iOS uygulaması)
-- =====================================================================================

CREATE TABLE devices (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id       uuid NOT NULL REFERENCES customers (id),
    platform          device_platform NOT NULL,
    fingerprint_hash  bytea NOT NULL CHECK (octet_length(fingerprint_hash) = 32),
    display_name      text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 100),
    -- Komut imzalama için cihazın açık anahtarı: Windows = Ed25519, iOS = Secure Enclave P-256.
    public_key        bytea,
    app_version       text,
    os_version        text,
    first_seen_at     timestamptz NOT NULL DEFAULT now(),
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    revoked_at        timestamptz,
    UNIQUE (customer_id, platform, fingerprint_hash)
);
CREATE INDEX ix_devices_customer ON devices (customer_id) WHERE revoked_at IS NULL;

-- Masaüstü motoru ile iOS uygulaması arasındaki eşleştirme. iOS'tan gelen komutlar,
-- yalnızca eşleştirilmiş cihazın anahtarıyla imzalanmışsa motor tarafından kabul edilir.
CREATE TABLE device_pairings (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    engine_device_id    uuid NOT NULL REFERENCES devices (id),
    companion_device_id uuid NOT NULL REFERENCES devices (id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    revoked_at          timestamptz,
    CHECK (engine_device_id <> companion_device_id)
);
CREATE UNIQUE INDEX ux_device_pairings_live
    ON device_pairings (engine_device_id, companion_device_id) WHERE revoked_at IS NULL;

CREATE FUNCTION device_pairings_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    engine_row    devices%ROWTYPE;
    companion_row devices%ROWTYPE;
BEGIN
    SELECT * INTO engine_row FROM devices WHERE id = NEW.engine_device_id;
    SELECT * INTO companion_row FROM devices WHERE id = NEW.companion_device_id;
    IF engine_row.platform <> 'windows' OR companion_row.platform <> 'ios' THEN
        RAISE EXCEPTION 'Eşleştirme bir Windows motoru ile bir iOS cihazı arasında olmalı'
            USING ERRCODE = 'check_violation';
    END IF;
    IF engine_row.customer_id <> companion_row.customer_id THEN
        RAISE EXCEPTION 'Eşleştirilen cihazlar aynı müşteriye ait olmalı'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER trg_device_pairings_guard BEFORE INSERT ON device_pairings
    FOR EACH ROW EXECUTE FUNCTION device_pairings_guard();

CREATE TABLE push_tokens (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id    uuid NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    apns_token   text NOT NULL UNIQUE,
    environment  text NOT NULL CHECK (environment IN ('sandbox', 'production')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz
);

CREATE TABLE customer_sessions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id         uuid NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    refresh_token_hash  bytea NOT NULL UNIQUE CHECK (octet_length(refresh_token_hash) = 32),
    client_kind         text NOT NULL CHECK (client_kind IN ('web', 'windows', 'ios')),
    device_id           uuid REFERENCES devices (id),
    ip                  inet,
    user_agent          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    last_used_at        timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    revoked_at          timestamptz
);
CREATE INDEX ix_customer_sessions_live ON customer_sessions (customer_id) WHERE revoked_at IS NULL;

-- =====================================================================================
-- Yöneticiler (müşteri girişinden tamamen ayrı tablo, oturum ve yetki sistemi)
-- =====================================================================================

CREATE TABLE admin_users (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email               citext NOT NULL UNIQUE,
    full_name           text NOT NULL,
    password_hash       text NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
    totp_secret_enc     bytea,
    totp_confirmed_at   timestamptz,
    status              admin_status NOT NULL DEFAULT 'invited',
    failed_login_count  integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until        timestamptz,
    created_by          uuid REFERENCES admin_users (id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    last_login_at       timestamptz,
    -- İki aşamalı doğrulama kurulmadan hiçbir yönetici hesabı aktif olamaz.
    CONSTRAINT admin_users_active_requires_2fa
        CHECK (status <> 'active' OR (totp_secret_enc IS NOT NULL AND totp_confirmed_at IS NOT NULL))
);
CREATE TRIGGER trg_admin_users_updated_at BEFORE UPDATE ON admin_users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE admin_recovery_codes (
    admin_id    uuid NOT NULL REFERENCES admin_users (id) ON DELETE CASCADE,
    code_hash   bytea NOT NULL CHECK (octet_length(code_hash) = 32),
    created_at  timestamptz NOT NULL DEFAULT now(),
    used_at     timestamptz,
    PRIMARY KEY (admin_id, code_hash)
);

-- Yönetici oturumu yalnızca 2FA doğrulandıktan sonra oluşturulur (mfa_verified_at zorunlu).
CREATE TABLE admin_sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id        uuid NOT NULL REFERENCES admin_users (id) ON DELETE CASCADE,
    token_hash      bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
    mfa_verified_at timestamptz NOT NULL,
    ip              inet,
    user_agent      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    CHECK (expires_at <= created_at + interval '12 hours')
);

CREATE TABLE admin_permissions (
    code        text PRIMARY KEY CHECK (code ~ '^[a-z_]+\.[a-z_]+$'),
    description text NOT NULL
);

CREATE TABLE admin_roles (
    code        text PRIMARY KEY CHECK (code ~ '^[a-z_]+$'),
    name        text NOT NULL,
    description text NOT NULL
);

CREATE TABLE admin_role_permissions (
    role_code       text NOT NULL REFERENCES admin_roles (code) ON DELETE CASCADE,
    permission_code text NOT NULL REFERENCES admin_permissions (code) ON DELETE CASCADE,
    PRIMARY KEY (role_code, permission_code)
);

CREATE TABLE admin_user_roles (
    admin_id    uuid NOT NULL REFERENCES admin_users (id) ON DELETE CASCADE,
    role_code   text NOT NULL REFERENCES admin_roles (code),
    granted_by  uuid REFERENCES admin_users (id),
    granted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (admin_id, role_code)
);

CREATE VIEW admin_effective_permissions AS
SELECT DISTINCT ur.admin_id, rp.permission_code
FROM admin_user_roles ur
JOIN admin_role_permissions rp ON rp.role_code = ur.role_code
JOIN admin_users au ON au.id = ur.admin_id AND au.status = 'active';

-- =====================================================================================
-- Lisans paketleri
-- =====================================================================================

CREATE TABLE license_plans (
    code                    text PRIMARY KEY CHECK (code ~ '^[a-z0-9_]+$'),
    name                    text NOT NULL,
    duration_days           integer CHECK (duration_days IS NULL OR duration_days > 0), -- NULL = ömür boyu
    device_limit            smallint NOT NULL CHECK (device_limit BETWEEN 1 AND 10),     -- Windows motoru
    companion_device_limit  smallint NOT NULL DEFAULT 2 CHECK (companion_device_limit BETWEEN 0 AND 10), -- iOS
    is_trial                boolean NOT NULL DEFAULT false,
    price_minor             bigint CHECK (price_minor >= 0),   -- kuruş/sent cinsinden
    currency                char(3) NOT NULL DEFAULT 'USD' CHECK (currency ~ '^[A-Z]{3}$'),
    is_active               boolean NOT NULL DEFAULT false,
    features                jsonb NOT NULL DEFAULT '{}'::jsonb,
    sort_order              integer NOT NULL DEFAULT 0,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT license_plans_active_has_price CHECK (NOT is_active OR price_minor IS NOT NULL),
    CONSTRAINT license_plans_trial_is_short
        CHECK (NOT is_trial OR (duration_days IS NOT NULL AND duration_days <= 30))
);
CREATE TRIGGER trg_license_plans_updated_at BEFORE UPDATE ON license_plans
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================================
-- Siparişler ve ödemeler
-- =====================================================================================

CREATE TABLE orders (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_no              bigint GENERATED ALWAYS AS IDENTITY (START WITH 100001) UNIQUE,
    customer_id           uuid NOT NULL REFERENCES customers (id),
    status                order_status NOT NULL DEFAULT 'pending',
    currency              char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    subtotal_minor        bigint NOT NULL CHECK (subtotal_minor >= 0),
    discount_minor        bigint NOT NULL DEFAULT 0 CHECK (discount_minor >= 0),
    tax_minor             bigint NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
    total_minor           bigint NOT NULL,
    payment_provider      text NOT NULL,
    provider_checkout_id  text,
    billing_snapshot      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    paid_at               timestamptz,
    fulfilled_at          timestamptz,
    cancelled_at          timestamptz,
    CONSTRAINT orders_total CHECK (total_minor = subtotal_minor - discount_minor + tax_minor),
    CONSTRAINT orders_total_non_negative CHECK (total_minor >= 0),
    CONSTRAINT orders_fulfilled_after_paid CHECK (fulfilled_at IS NULL OR paid_at IS NOT NULL),
    UNIQUE (payment_provider, provider_checkout_id)
);
CREATE INDEX ix_orders_customer ON orders (customer_id, created_at DESC);
CREATE INDEX ix_orders_paid_at ON orders (paid_at) WHERE paid_at IS NOT NULL;
CREATE TRIGGER trg_orders_updated_at BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE order_items (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id          uuid NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    plan_code         text NOT NULL REFERENCES license_plans (code),
    quantity          integer NOT NULL CHECK (quantity BETWEEN 1 AND 1000),
    unit_price_minor  bigint NOT NULL CHECK (unit_price_minor >= 0),
    line_total_minor  bigint NOT NULL,
    CHECK (line_total_minor = quantity * unit_price_minor)
);
CREATE INDEX ix_order_items_order ON order_items (order_id);

CREATE TABLE payments (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id             uuid NOT NULL REFERENCES orders (id),
    provider             text NOT NULL,
    provider_payment_id  text NOT NULL,
    status               payment_status NOT NULL DEFAULT 'pending',
    amount_minor         bigint NOT NULL CHECK (amount_minor >= 0),
    refunded_minor       bigint NOT NULL DEFAULT 0,
    currency             char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    succeeded_at         timestamptz,
    CHECK (refunded_minor BETWEEN 0 AND amount_minor),
    UNIQUE (provider, provider_payment_id)
);
-- Bir sipariş için en fazla bir başarılı ödeme: aynı sipariş iki kez tahsil edilip
-- iki kez lisans üretilemez.
CREATE UNIQUE INDEX ux_payments_one_success_per_order ON payments (order_id)
    WHERE status IN ('succeeded', 'refunded', 'partially_refunded', 'disputed');
CREATE TRIGGER trg_payments_updated_at BEFORE UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE refunds (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id          uuid NOT NULL REFERENCES payments (id),
    provider_refund_id  text NOT NULL,
    amount_minor        bigint NOT NULL CHECK (amount_minor > 0),
    reason              text,
    status              text NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
    license_action      text NOT NULL CHECK (license_action IN ('cancel', 'keep', 'manual_review')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (payment_id, provider_refund_id)
);

-- Ödeme sağlayıcısından gelen webhook olayları. (provider, provider_event_id) tekil
-- olduğundan aynı olay iki kez işlenemez (idempotency). İmzası doğrulanmamış bir olay
-- asla "işlendi" olarak işaretlenemez.
CREATE TABLE payment_webhook_events (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider            text NOT NULL,
    provider_event_id   text NOT NULL,
    event_type          text NOT NULL,
    signature_valid     boolean NOT NULL,
    payload             jsonb NOT NULL,
    received_at         timestamptz NOT NULL DEFAULT now(),
    processed_at        timestamptz,
    attempts            integer NOT NULL DEFAULT 0,
    last_error          text,
    UNIQUE (provider, provider_event_id),
    CONSTRAINT webhook_processed_requires_valid_signature
        CHECK (processed_at IS NULL OR signature_valid)
);
CREATE INDEX ix_webhook_unprocessed ON payment_webhook_events (received_at)
    WHERE processed_at IS NULL AND signature_valid;

CREATE TABLE invoices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        uuid NOT NULL UNIQUE REFERENCES orders (id),
    invoice_no      text NOT NULL UNIQUE,
    issued_at       timestamptz NOT NULL DEFAULT now(),
    provider        text,          -- e-Arşiv / e-Fatura entegratörü veya ödeme sağlayıcısı
    external_id     text,
    pdf_object_key  text,          -- nesne deposundaki PDF anahtarı
    billing         jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- =====================================================================================
-- Lisanslar
-- =====================================================================================

-- 9.999.999.999 lisans kapasitesi: seri numarası dizisi tam olarak bu sınırda durur.
-- Lisans anahtarının kendisi 75 bit rastgelelik taşır (bkz. docs/04-veritabani-semasi.md).
CREATE SEQUENCE license_serial_seq AS bigint MINVALUE 1 MAXVALUE 9999999999 NO CYCLE;

CREATE TABLE license_batches (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_code         text NOT NULL REFERENCES license_plans (code),
    quantity          integer NOT NULL CHECK (quantity BETWEEN 1 AND 100000),
    purpose           text NOT NULL CHECK (purpose IN ('sale_pool', 'manual', 'promotion', 'replacement')),
    note              text,
    created_by_admin  uuid REFERENCES admin_users (id),
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE licenses (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    serial                  bigint NOT NULL UNIQUE DEFAULT nextval('license_serial_seq'),
    -- HMAC-SHA256(pepper, normalize(anahtar)). Anahtar doğrulama bu sütunla yapılır.
    key_hash                bytea NOT NULL UNIQUE CHECK (octet_length(key_hash) = 32),
    -- Müşteri panelinde yeniden gösterim için AES-256-GCM (zarf şifreleme) ile şifreli anahtar.
    key_ciphertext          bytea NOT NULL CHECK (octet_length(key_ciphertext) >= 29),
    key_hint                text NOT NULL CHECK (key_hint ~ '^ATI-\*{4}-\*{4}-\*{4}-[0-9A-Z]{4}$'),
    plan_code               text NOT NULL REFERENCES license_plans (code),
    batch_id                uuid REFERENCES license_batches (id),
    status                  license_status NOT NULL DEFAULT 'generated',
    customer_id             uuid REFERENCES customers (id),
    order_item_id           uuid REFERENCES order_items (id),
    order_item_unit         integer CHECK (order_item_unit >= 1),
    -- Satış anındaki paket koşulları (paket sonradan değişse de müşterinin hakkı korunur).
    duration_days           integer CHECK (duration_days IS NULL OR duration_days > 0),
    device_limit            smallint NOT NULL CHECK (device_limit BETWEEN 1 AND 10),
    companion_device_limit  smallint NOT NULL CHECK (companion_device_limit BETWEEN 0 AND 10),
    sold_at                 timestamptz,
    activated_at            timestamptz,
    expires_at              timestamptz,
    frozen_at               timestamptz,
    frozen_reason           text,
    status_before_freeze    license_status,
    cancelled_at            timestamptz,
    cancel_reason           text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    version                 integer NOT NULL DEFAULT 1,
    CONSTRAINT licenses_owner_required
        CHECK (status NOT IN ('sold', 'active', 'expired') OR customer_id IS NOT NULL),
    CONSTRAINT licenses_unsold_has_no_owner
        CHECK (status NOT IN ('generated', 'ready_for_sale')
               OR (customer_id IS NULL AND order_item_id IS NULL AND sold_at IS NULL)),
    CONSTRAINT licenses_sold_has_timestamp
        CHECK (status NOT IN ('sold', 'active', 'expired') OR sold_at IS NOT NULL),
    CONSTRAINT licenses_active_has_activation
        CHECK (status <> 'active' OR activated_at IS NOT NULL),
    CONSTRAINT licenses_timed_active_has_expiry
        CHECK (status <> 'active' OR duration_days IS NULL OR expires_at IS NOT NULL),
    CONSTRAINT licenses_order_unit_pair
        CHECK ((order_item_id IS NULL) = (order_item_unit IS NULL)),
    CONSTRAINT licenses_frozen_consistency
        CHECK ((status = 'frozen') = (frozen_at IS NOT NULL AND status_before_freeze IS NOT NULL)),
    CONSTRAINT licenses_cancelled_consistency
        CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
    -- Bir sipariş kalemindeki her birim için en fazla bir lisans: aynı ödeme tekrar
    -- işlense bile ikinci lisans tahsis edilemez.
    UNIQUE (order_item_id, order_item_unit)
);
CREATE INDEX ix_licenses_pool ON licenses (plan_code, serial) WHERE status = 'ready_for_sale';
CREATE INDEX ix_licenses_customer ON licenses (customer_id) WHERE customer_id IS NOT NULL;
CREATE INDEX ix_licenses_expiry ON licenses (expires_at) WHERE status = 'active';

-- İzin verilen durum geçişleri.
CREATE TABLE license_status_transitions (
    from_status license_status NOT NULL,
    to_status   license_status NOT NULL,
    PRIMARY KEY (from_status, to_status)
);
INSERT INTO license_status_transitions (from_status, to_status) VALUES
    ('generated',      'ready_for_sale'),
    ('generated',      'sold'),          -- satın alma anında üret-ve-ata
    ('generated',      'cancelled'),
    ('ready_for_sale', 'sold'),
    ('ready_for_sale', 'frozen'),
    ('ready_for_sale', 'cancelled'),
    ('sold',           'active'),
    ('sold',           'frozen'),
    ('sold',           'cancelled'),
    ('active',         'expired'),
    ('active',         'frozen'),
    ('active',         'cancelled'),
    ('expired',        'active'),        -- süre uzatma / yenileme
    ('expired',        'frozen'),
    ('expired',        'cancelled'),
    ('frozen',         'ready_for_sale'),
    ('frozen',         'sold'),
    ('frozen',         'active'),
    ('frozen',         'expired'),
    ('frozen',         'cancelled');
-- 'cancelled' son durumdur; hiçbir geçiş tanımlı değildir.

CREATE FUNCTION licenses_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    item_quantity integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('generated', 'ready_for_sale', 'sold') THEN
            RAISE EXCEPTION 'Yeni lisans % durumunda oluşturulamaz', NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
    ELSE
        -- Değiştirilemez alanlar.
        IF NEW.serial <> OLD.serial OR NEW.key_hash <> OLD.key_hash
           OR NEW.key_ciphertext <> OLD.key_ciphertext OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'Lisans anahtarı ve seri numarası değiştirilemez'
                USING ERRCODE = 'check_violation';
        END IF;
        -- Sahiplik bir kez atanır; başka müşteriye aktarılamaz (ikinci satış engeli).
        IF OLD.customer_id IS NOT NULL AND NEW.customer_id IS DISTINCT FROM OLD.customer_id THEN
            RAISE EXCEPTION 'Lisans sahibi değiştirilemez' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.order_item_id IS NOT NULL AND (NEW.order_item_id IS DISTINCT FROM OLD.order_item_id
           OR NEW.order_item_unit IS DISTINCT FROM OLD.order_item_unit) THEN
            RAISE EXCEPTION 'Lisansın sipariş bağlantısı değiştirilemez'
                USING ERRCODE = 'check_violation';
        END IF;

        IF NEW.status <> OLD.status THEN
            IF NOT EXISTS (
                SELECT 1 FROM license_status_transitions
                WHERE from_status = OLD.status AND to_status = NEW.status
            ) THEN
                RAISE EXCEPTION 'Geçersiz lisans durum geçişi: % -> %', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.status = 'frozen' AND NEW.status NOT IN ('cancelled', 'expired')
               AND NEW.status <> OLD.status_before_freeze THEN
                RAISE EXCEPTION 'Dondurma kaldırılınca lisans önceki durumuna (%) dönmeli',
                    OLD.status_before_freeze USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.status = 'frozen' THEN
                NEW.status_before_freeze := OLD.status;
                NEW.frozen_at := COALESCE(NEW.frozen_at, now());
            ELSIF OLD.status = 'frozen' THEN
                NEW.status_before_freeze := NULL;
                NEW.frozen_at := NULL;
                NEW.frozen_reason := NULL;
            END IF;
            IF NEW.status = 'cancelled' THEN
                NEW.cancelled_at := COALESCE(NEW.cancelled_at, now());
            END IF;
        END IF;
        NEW.version := OLD.version + 1;
        NEW.updated_at := now();
    END IF;

    IF NEW.order_item_id IS NOT NULL THEN
        SELECT quantity INTO item_quantity FROM order_items WHERE id = NEW.order_item_id;
        IF NEW.order_item_unit > item_quantity THEN
            RAISE EXCEPTION 'Sipariş kalemi yalnızca % lisans içerir', item_quantity
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER trg_licenses_guard BEFORE INSERT OR UPDATE ON licenses
    FOR EACH ROW EXECUTE FUNCTION licenses_guard();

-- Lisans durum geçmişi (değiştirilemez).
CREATE TABLE license_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    license_id  uuid NOT NULL REFERENCES licenses (id),
    from_status license_status,
    to_status   license_status NOT NULL,
    actor_type  actor_type NOT NULL,
    actor_id    text,
    details     jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_license_events_license ON license_events (license_id, id);

CREATE FUNCTION licenses_record_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' OR NEW.status <> OLD.status THEN
        INSERT INTO license_events (license_id, from_status, to_status, actor_type, actor_id, details)
        VALUES (
            NEW.id,
            CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.status END,
            NEW.status,
            current_actor_type(),
            current_actor_id(),
            jsonb_strip_nulls(jsonb_build_object(
                'frozen_reason', NEW.frozen_reason,
                'cancel_reason', NEW.cancel_reason,
                'expires_at', NEW.expires_at
            ))
        );
    END IF;
    RETURN NULL;
END
$$;
CREATE TRIGGER trg_licenses_record_event AFTER INSERT OR UPDATE ON licenses
    FOR EACH ROW EXECUTE FUNCTION licenses_record_event();

-- Lisans aktivasyonları (cihaz bağlama).
CREATE TABLE license_activations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    license_id          uuid NOT NULL REFERENCES licenses (id),
    device_id           uuid NOT NULL REFERENCES devices (id),
    activated_at        timestamptz NOT NULL DEFAULT now(),
    last_validated_at   timestamptz,
    deactivated_at      timestamptz,
    deactivated_by      actor_type,
    deactivation_reason text,
    CHECK ((deactivated_at IS NULL) = (deactivated_by IS NULL))
);
CREATE UNIQUE INDEX ux_license_activations_live
    ON license_activations (license_id, device_id) WHERE deactivated_at IS NULL;
CREATE INDEX ix_license_activations_device ON license_activations (device_id)
    WHERE deactivated_at IS NULL;

-- Cihaz limiti ve sahiplik kontrolü. Lisans satırı kilitlendiği için eşzamanlı iki
-- aktivasyon isteği limiti aşamaz.
CREATE FUNCTION license_activations_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    lic           licenses%ROWTYPE;
    dev           devices%ROWTYPE;
    used          integer;
    allowed       integer;
BEGIN
    SELECT * INTO lic FROM licenses WHERE id = NEW.license_id FOR UPDATE;
    SELECT * INTO dev FROM devices WHERE id = NEW.device_id;
    IF lic.status NOT IN ('sold', 'active') THEN
        RAISE EXCEPTION 'Lisans % durumunda; aktivasyon yapılamaz', lic.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF dev.customer_id IS DISTINCT FROM lic.customer_id THEN
        RAISE EXCEPTION 'Cihaz ve lisans aynı müşteriye ait değil'
            USING ERRCODE = 'check_violation';
    END IF;
    IF dev.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'Cihaz iptal edilmiş' USING ERRCODE = 'check_violation';
    END IF;
    SELECT count(*) INTO used
    FROM license_activations a
    JOIN devices d ON d.id = a.device_id
    WHERE a.license_id = NEW.license_id
      AND a.deactivated_at IS NULL
      AND d.platform = dev.platform;
    allowed := CASE WHEN dev.platform = 'windows' THEN lic.device_limit
                    ELSE lic.companion_device_limit END;
    IF used >= allowed THEN
        RAISE EXCEPTION 'Cihaz limiti aşıldı (% / %)', used, allowed
            USING ERRCODE = 'check_violation', HINT = 'device_limit_exceeded';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER trg_license_activations_guard BEFORE INSERT ON license_activations
    FOR EACH ROW EXECUTE FUNCTION license_activations_guard();

-- =====================================================================================
-- E-posta gönderim kuyruğu (transactional outbox)
-- =====================================================================================
-- Lisans anahtarı bu tabloda düz metin olarak TUTULMAZ; payload yalnızca license_id içerir,
-- gönderici iş parçacığı anahtarı gönderim anında çözer.
CREATE TABLE email_outbox (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dedupe_key          text NOT NULL UNIQUE,
    to_email            citext NOT NULL,
    template            text NOT NULL,
    payload             jsonb NOT NULL DEFAULT '{}'::jsonb,
    status              outbox_status NOT NULL DEFAULT 'pending',
    attempts            integer NOT NULL DEFAULT 0,
    next_attempt_at     timestamptz NOT NULL DEFAULT now(),
    sent_at             timestamptz,
    provider_message_id text,
    last_error          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (NOT (payload ?| ARRAY['license_key', 'key', 'password']))
);
CREATE INDEX ix_email_outbox_due ON email_outbox (next_attempt_at) WHERE status IN ('pending', 'failed');

-- =====================================================================================
-- Sistem ayarları
-- =====================================================================================

CREATE TABLE system_settings (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  uuid REFERENCES admin_users (id)
);

-- =====================================================================================
-- Denetim kaydı (hash zincirli, yalnızca ekleme yapılabilir)
-- =====================================================================================

CREATE TABLE audit_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    actor_type   actor_type NOT NULL,
    actor_id     text,
    action       text NOT NULL CHECK (action ~ '^[a-z_]+(\.[a-z_]+)+$'),
    target_type  text,
    target_id    text,
    ip           inet,
    user_agent   text,
    details      jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash    bytea NOT NULL,
    hash         bytea NOT NULL UNIQUE
);
CREATE INDEX ix_audit_log_target ON audit_log (target_type, target_id);
CREATE INDEX ix_audit_log_actor ON audit_log (actor_type, actor_id, occurred_at);

CREATE FUNCTION audit_log_row_digest(
    p_prev bytea, p_id bigint, p_at timestamptz, p_actor_type actor_type, p_actor_id text,
    p_action text, p_target_type text, p_target_id text, p_details jsonb
) RETURNS bytea
LANGUAGE sql STABLE AS $$
    SELECT sha256(p_prev || convert_to(concat_ws(chr(31),
        p_id::text,
        (extract(epoch FROM p_at) * 1000000)::bigint::text,
        p_actor_type::text,
        COALESCE(p_actor_id, ''),
        p_action,
        COALESCE(p_target_type, ''),
        COALESCE(p_target_id, ''),
        p_details::text
    ), 'UTF8'))
$$;

CREATE FUNCTION audit_log_chain() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    last_hash bytea;
BEGIN
    -- Zincir sırasını korumak için eklemeleri seri hale getir (yönetim işlemleri düşük hacimlidir).
    PERFORM pg_advisory_xact_lock(hashtext('ati.audit_log'));
    SELECT hash INTO last_hash FROM audit_log ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := COALESCE(last_hash, '\x0000000000000000000000000000000000000000000000000000000000000000'::bytea);
    NEW.hash := audit_log_row_digest(NEW.prev_hash, NEW.id, NEW.occurred_at, NEW.actor_type,
        NEW.actor_id, NEW.action, NEW.target_type, NEW.target_id, NEW.details);
    RETURN NEW;
END
$$;
CREATE TRIGGER trg_audit_log_chain BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_chain();

CREATE FUNCTION reject_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% tablosu yalnızca ekleme yapılabilir; % reddedildi', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END
$$;
CREATE TRIGGER trg_audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_license_events_immutable BEFORE UPDATE OR DELETE ON license_events
    FOR EACH ROW EXECUTE FUNCTION reject_modification();
CREATE TRIGGER trg_license_events_no_truncate BEFORE TRUNCATE ON license_events
    FOR EACH STATEMENT EXECUTE FUNCTION reject_modification();

-- Zinciri doğrular; kırık ilk kaydın id'sini, zincir sağlamsa NULL döner.
CREATE FUNCTION audit_log_verify() RETURNS bigint
LANGUAGE plpgsql STABLE AS $$
DECLARE
    rec       audit_log%ROWTYPE;
    expected  bytea := '\x0000000000000000000000000000000000000000000000000000000000000000'::bytea;
BEGIN
    FOR rec IN SELECT * FROM audit_log ORDER BY id LOOP
        IF rec.prev_hash <> expected OR rec.hash <> audit_log_row_digest(rec.prev_hash, rec.id,
            rec.occurred_at, rec.actor_type, rec.actor_id, rec.action, rec.target_type,
            rec.target_id, rec.details) THEN
            RETURN rec.id;
        END IF;
        expected := rec.hash;
    END LOOP;
    RETURN NULL;
END
$$;

-- =====================================================================================
-- Yönetici raporları
-- =====================================================================================

CREATE VIEW admin_license_stats AS
SELECT plan_code, status, count(*) AS license_count
FROM licenses
GROUP BY plan_code, status;

CREATE VIEW admin_sales_daily AS
SELECT date_trunc('day', paid_at) AS day,
       currency,
       count(*) AS order_count,
       sum(total_minor) AS revenue_minor
FROM orders
WHERE status IN ('paid', 'fulfilled', 'partially_refunded')
GROUP BY 1, 2;

CREATE VIEW admin_active_usage AS
SELECT d.platform,
       count(DISTINCT a.device_id) AS active_devices,
       count(DISTINCT l.customer_id) AS active_customers
FROM license_activations a
JOIN devices d ON d.id = a.device_id
JOIN licenses l ON l.id = a.license_id
WHERE a.deactivated_at IS NULL
  AND l.status = 'active'
  AND a.last_validated_at > now() - interval '7 days'
GROUP BY d.platform;
