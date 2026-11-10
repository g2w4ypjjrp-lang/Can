-- İndirim kuponları. Yöneticinin oluşturduğu kodlar siparişte indirim uygular (yüzde ya da tutar).
-- Ortaklık/tanıtım için kişiye özel kod verilip kullanım sayısı panelden izlenebilir.
--
-- Kullanım sayısı ayrıca tutulmaz: siparişlerden sayılır (ödenmiş/teslim edilmiş siparişler ve
-- son 2 saatte açılmış, ödemesi bekleyen siparişler). Böylece iade/iptal edilen ya da yarım kalan
-- siparişler hakkı tüketmez. Aynı koda eşzamanlı başvurular uygulamada danışma kilidiyle sıralanır.

CREATE TABLE coupons (
    code              text PRIMARY KEY CHECK (code ~ '^[A-Z0-9][A-Z0-9-]{2,31}$'),
    percent_off       integer CHECK (percent_off BETWEEN 1 AND 100),
    amount_off_minor  bigint CHECK (amount_off_minor > 0),
    currency          char(3) CHECK (currency ~ '^[A-Z]{3}$'),
    plan_codes        text[] NOT NULL DEFAULT '{}',
    max_redemptions   integer CHECK (max_redemptions > 0),
    valid_from        timestamptz,
    valid_until       timestamptz,
    is_active         boolean NOT NULL DEFAULT true,
    note              text NOT NULL DEFAULT '' CHECK (length(note) <= 200),
    created_by        uuid REFERENCES admin_users (id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coupons_one_kind CHECK (
        (percent_off IS NOT NULL AND amount_off_minor IS NULL AND currency IS NULL)
        OR (percent_off IS NULL AND amount_off_minor IS NOT NULL AND currency IS NOT NULL)
    ),
    CONSTRAINT coupons_window CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_until > valid_from)
);
CREATE TRIGGER trg_coupons_updated_at BEFORE UPDATE ON coupons
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE orders ADD COLUMN coupon_code text REFERENCES coupons (code);
ALTER TABLE orders ADD CONSTRAINT orders_coupon_discount
    CHECK (coupon_code IS NOT NULL OR discount_minor = 0);
CREATE INDEX ix_orders_coupon ON orders (coupon_code, status) WHERE coupon_code IS NOT NULL;

INSERT INTO admin_permissions (code, description) VALUES
    ('coupon.manage', 'İndirim kuponu oluşturma ve yönetme');

-- Paket/fiyat yönetebilen her rol kupon da yönetebilir.
INSERT INTO admin_role_permissions (role_code, permission_code)
SELECT role_code, 'coupon.manage' FROM admin_role_permissions WHERE permission_code = 'plan.manage';
