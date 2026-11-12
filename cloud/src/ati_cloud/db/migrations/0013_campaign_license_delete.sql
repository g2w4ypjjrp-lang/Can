-- Yönetim panelinden lisans silme: denetim zinciri (license_events) değiştirilemez olduğu için
-- lisans satırı fiziksel olarak silinmez; iptal edilir ve deleted_at ile tüm listelerden kalkar.
-- Anahtar kalıcı olarak geçersizdir; muhasebe ve denetim kayıtları korunur.
ALTER TABLE licenses ADD COLUMN deleted_at timestamptz;
ALTER TABLE licenses ADD CONSTRAINT licenses_deleted_is_cancelled
    CHECK (deleted_at IS NULL OR status = 'cancelled');
CREATE INDEX ix_licenses_not_deleted ON licenses (serial DESC) WHERE deleted_at IS NULL;

-- Genel indirim kampanyası (system_settings 'campaign') siparişte kaydedilir.
ALTER TABLE orders ADD COLUMN campaign_percent smallint
    CHECK (campaign_percent IS NULL OR campaign_percent BETWEEN 1 AND 90);
