-- Aşama 18: uzaktan kontrol mesajları uçtan uca şifreli. Telefonun P-256 anahtar anlaşması
-- açık anahtarı (X9.63, base64) eşleştirmede kaydedilir. Bu sütun boş olan (şifreleme öncesi
-- eşleşmiş) cihazlara mesaj gönderilmez; yeniden eşleştirme gerekir.
ALTER TABLE remote_devices ADD COLUMN kx_key TEXT;
