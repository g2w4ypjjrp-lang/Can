-- İndirme: uygulama sürümleri (Windows kurulum paketi, iPhone uygulaması).
--
-- Yönetici panelinden taslak olarak eklenir ve güncel TOTP koduyla yayınlanır; web sitesinin
-- indirme sayfası yayındaki en son sürümü gösterir. Yayınlanmış bir sürümün dosya bilgileri
-- (adres, SHA-256, boyut) değiştirilemez: yanlışsa geri çekilir ve yeni sürüm eklenir. Böylece
-- müşterinin indirdiği dosyanın özeti, sayfada gördüğüyle her zaman aynı kalır.

INSERT INTO admin_permissions (code, description) VALUES
    ('release.manage', 'Uygulama sürümlerini (indirme sayfası) yönetme');

INSERT INTO admin_role_permissions (role_code, permission_code) VALUES
    ('super_admin', 'release.manage');

CREATE TABLE app_releases (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    platform      text NOT NULL CHECK (platform IN ('windows', 'ios')),
    version       text NOT NULL CHECK (version ~ '^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,6}(-[0-9A-Za-z.]{1,20})?$'),
    download_url  text NOT NULL CHECK (download_url ~ '^https://[^\s]+$' AND length(download_url) <= 500),
    sha256        text CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes    bigint CHECK (size_bytes > 0 AND size_bytes <= 4294967296),
    min_os        text NOT NULL DEFAULT '' CHECK (length(min_os) <= 80),
    notes         text NOT NULL DEFAULT '' CHECK (length(notes) <= 4000),
    signed        boolean NOT NULL DEFAULT false,
    status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'withdrawn')),
    published_at  timestamptz,
    withdrawn_at  timestamptz,
    created_by    uuid REFERENCES admin_users (id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, version),
    -- Windows kurulum paketi indirilen dosyadır: özet ve boyut zorunlu (müşteri doğrulayabilsin).
    CONSTRAINT app_releases_windows_has_digest
        CHECK (platform <> 'windows' OR (sha256 IS NOT NULL AND size_bytes IS NOT NULL)),
    CONSTRAINT app_releases_published_has_time
        CHECK (status <> 'published' OR published_at IS NOT NULL)
);

CREATE INDEX ix_app_releases_latest
    ON app_releases (platform, published_at DESC) WHERE status = 'published';

-- Yayınlanmış/geri çekilmiş sürümde dosya bilgileri değişmez (uygulama hatasına karşı ikinci kat).
CREATE FUNCTION app_releases_freeze_published() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'draft' AND (
        NEW.platform IS DISTINCT FROM OLD.platform OR
        NEW.version IS DISTINCT FROM OLD.version OR
        NEW.download_url IS DISTINCT FROM OLD.download_url OR
        NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
        NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR
        NEW.signed IS DISTINCT FROM OLD.signed
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

CREATE TRIGGER app_releases_freeze
    BEFORE UPDATE ON app_releases
    FOR EACH ROW EXECUTE FUNCTION app_releases_freeze_published();

CREATE FUNCTION app_releases_no_delete_published() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'draft' THEN
        RAISE EXCEPTION 'yayınlanmış sürüm silinemez; geri çekin'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'app_releases_frozen';
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER app_releases_no_delete
    BEFORE DELETE ON app_releases
    FOR EACH ROW EXECUTE FUNCTION app_releases_no_delete_published();
