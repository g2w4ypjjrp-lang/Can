-- Otomatik güncelleme: Windows sürümünün güncelleme imzası (Tauri updater, minisign/Ed25519).
--
-- İmza, sunucudaki güncelleme anahtarıyla (C:\ATI\ayarlar, yonet.ps1 surum-hazirla) atılır;
-- uygulama yalnızca gömülü açık anahtarla doğrulanan dosyayı kurar. Yayınlanan sürümün imzası
-- da dosya bilgileri gibi değiştirilemez.

ALTER TABLE app_releases ADD COLUMN update_signature text
    CHECK (update_signature IS NULL OR length(update_signature) BETWEEN 100 AND 4000);

CREATE OR REPLACE FUNCTION app_releases_freeze_published() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'draft' AND (
        NEW.platform IS DISTINCT FROM OLD.platform OR
        NEW.version IS DISTINCT FROM OLD.version OR
        NEW.download_url IS DISTINCT FROM OLD.download_url OR
        NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
        NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR
        NEW.signed IS DISTINCT FROM OLD.signed OR
        NEW.update_signature IS DISTINCT FROM OLD.update_signature
    ) THEN
        RAISE EXCEPTION 'yayınlanmış sürümün dosya bilgileri değiştirilemez'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'app_releases_frozen';
    END IF;
    IF NEW.status = 'draft' AND OLD.status <> 'draft' THEN
        RAISE EXCEPTION 'yayınlanmış sürüm taslağa döndürülemez'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'app_releases_frozen';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
