-- Aşama 15: motorun imzalı lisans istekleri için tekrar oynatma koruması.
-- Yenileme ve cihaz bırakma istekleri, aktivasyon başına kesin artan zaman damgası taşır;
-- yakalanıp yeniden gönderilen istek reddedilir.

ALTER TABLE license_activations ADD COLUMN last_request_ms bigint;

-- Müşterinin panelden cihaz kaldırma sayısı sayılırken kullanılır (30 günlük sınır).
CREATE INDEX ix_license_activations_customer_resets
    ON license_activations (license_id, deactivated_at)
    WHERE deactivated_by = 'customer';
