-- İsteğe bağlı hata raporları (masaüstü uygulamasında kullanıcı açarsa). Aynı hata (parmak izi)
-- tek satırda toplanır ve sayılır. IP adresi, cihaz ya da müşteri kimliği saklanmaz; metinler
-- uygulamada ve sunucuda ayıklanmıştır.

CREATE TABLE crash_reports (
    fingerprint   text PRIMARY KEY CHECK (fingerprint ~ '^[0-9a-f]{32}$'),
    app           text NOT NULL CHECK (app IN ('engine', 'desktop')),
    component     text NOT NULL CHECK (length(component) <= 120),
    error_type    text NOT NULL CHECK (length(error_type) <= 120),
    message       text NOT NULL CHECK (length(message) <= 500),
    stack         text NOT NULL CHECK (length(stack) <= 8000),
    first_version text NOT NULL CHECK (length(first_version) <= 40),
    last_version  text NOT NULL CHECK (length(last_version) <= 40),
    os            text NOT NULL CHECK (length(os) <= 60),
    occurrences   integer NOT NULL DEFAULT 1 CHECK (occurrences >= 1),
    status        text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'seen', 'fixed', 'ignored')),
    first_seen    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_crash_reports_last_seen ON crash_reports (last_seen DESC);

INSERT INTO admin_permissions (code, description) VALUES
    ('crash.manage', 'Uygulama hata raporlarını görme ve durumunu değiştirme');
INSERT INTO admin_role_permissions (role_code, permission_code) VALUES
    ('super_admin', 'crash.manage');
