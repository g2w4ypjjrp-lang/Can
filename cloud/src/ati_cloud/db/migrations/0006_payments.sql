-- Aşama 17: ödeme ve teslim.
--
-- * orders.review_reason: ödeme alındı ama otomatik teslim yapılmadı (tutar uyuşmazlığı,
--   ikinci tahsilat, bilinmeyen sağlayıcı) → yönetici incelemesi.
-- * orders.checkout_url: sağlayıcının ödeme sayfası (müşteri aynı siparişe geri dönebilsin).
-- * İade kaydı yönetici kimliğini taşır; bekleyen iade tutarı iade edilebilir tutardan düşülür.

ALTER TABLE orders ADD COLUMN review_reason text
    CHECK (review_reason IS NULL OR review_reason IN (
        'amount_mismatch', 'duplicate_payment', 'provider_mismatch'));
ALTER TABLE orders ADD COLUMN checkout_url text;
CREATE INDEX ix_orders_review ON orders (created_at) WHERE review_reason IS NOT NULL;
CREATE INDEX ix_orders_pending ON orders (created_at) WHERE status = 'pending';

ALTER TABLE refunds ADD COLUMN requested_by uuid REFERENCES admin_users (id);
ALTER TABLE refunds ADD COLUMN completed_at timestamptz;
ALTER TABLE refunds ADD COLUMN last_error text;
CREATE INDEX ix_refunds_payment ON refunds (payment_id);
