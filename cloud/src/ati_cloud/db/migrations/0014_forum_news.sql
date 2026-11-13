-- Forum: müşterilerin açtığı konular ve yanıtlar yönetici onayından sonra yayımlanır.
-- Ekip konuları (yönetim panelinden, ör. paylaşılan coin haberleri) doğrudan yayımlanır.
-- Müşteri silinince konu ve yanıtları da silinir (manage.delete_customer).

CREATE TABLE forum_topics (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    number           bigint GENERATED ALWAYS AS IDENTITY UNIQUE,  -- adres: /forum/<number>
    customer_id      uuid REFERENCES customers (id) ON DELETE SET NULL,
    author_kind      text NOT NULL CHECK (author_kind IN ('customer', 'team')),
    author_name      text NOT NULL CHECK (length(author_name) BETWEEN 2 AND 40),
    category         text NOT NULL
        CHECK (category IN ('genel', 'strateji', 'soru', 'yeni-coin', 'haber')),
    title            text NOT NULL CHECK (length(title) BETWEEN 5 AND 120),
    body             text NOT NULL CHECK (length(body) BETWEEN 10 AND 5000),
    coin_symbol      text CHECK (coin_symbol ~ '^[A-Z0-9]{2,12}$'),
    source_name      text CHECK (length(source_name) <= 60),
    source_url       text CHECK (source_url ~ '^https://[^\s]+$' AND length(source_url) <= 500),
    status           text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'hidden')),
    moderation_note  text CHECK (length(moderation_note) <= 300),
    moderated_by     uuid REFERENCES admin_users (id),
    moderated_at     timestamptz,
    pinned           boolean NOT NULL DEFAULT false,
    locked           boolean NOT NULL DEFAULT false,
    flags            text[] NOT NULL DEFAULT '{}',   -- otomatik uyarılar (yöneticiye)
    view_count       integer NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    published_at     timestamptz,
    CONSTRAINT forum_topics_published CHECK (status <> 'approved' OR published_at IS NOT NULL)
);
CREATE INDEX ix_forum_topics_public ON forum_topics (pinned DESC, published_at DESC)
    WHERE status = 'approved';
CREATE INDEX ix_forum_topics_pending ON forum_topics (created_at) WHERE status = 'pending';
CREATE INDEX ix_forum_topics_customer ON forum_topics (customer_id, created_at DESC);

CREATE TABLE forum_replies (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id         uuid NOT NULL REFERENCES forum_topics (id) ON DELETE CASCADE,
    customer_id      uuid REFERENCES customers (id) ON DELETE SET NULL,
    author_kind      text NOT NULL CHECK (author_kind IN ('customer', 'team')),
    author_name      text NOT NULL CHECK (length(author_name) BETWEEN 2 AND 40),
    body             text NOT NULL CHECK (length(body) BETWEEN 2 AND 3000),
    status           text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'hidden')),
    moderation_note  text CHECK (length(moderation_note) <= 300),
    moderated_by     uuid REFERENCES admin_users (id),
    moderated_at     timestamptz,
    flags            text[] NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    published_at     timestamptz,
    CONSTRAINT forum_replies_published CHECK (status <> 'approved' OR published_at IS NOT NULL)
);
CREATE INDEX ix_forum_replies_topic ON forum_replies (topic_id, published_at)
    WHERE status = 'approved';
CREATE INDEX ix_forum_replies_pending ON forum_replies (created_at) WHERE status = 'pending';
CREATE INDEX ix_forum_replies_customer ON forum_replies (customer_id, created_at DESC);

-- Coin haberleri: herkese açık kaynaklardan (Binance duyuruları ve yeni işlem çiftleri, kripto
-- haber sitelerinin RSS akışları) düzenli çekilir. Yalnızca başlık, kısa özet ve bağlantı
-- saklanır; yönetici beğendiğini "Paylaş" ile foruma ekip konusu olarak ekler.
CREATE TABLE coin_news (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source        text NOT NULL CHECK (length(source) <= 40),
    external_id   text NOT NULL CHECK (length(external_id) <= 300),
    kind          text NOT NULL CHECK (kind IN ('listing', 'news')),
    title         text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
    summary       text NOT NULL DEFAULT '' CHECK (length(summary) <= 600),
    url           text NOT NULL CHECK (url ~ '^https://[^\s]+$' AND length(url) <= 500),
    symbols       text[] NOT NULL DEFAULT '{}',
    published_at  timestamptz NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    status        text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'shared', 'dismissed')),
    topic_id      uuid REFERENCES forum_topics (id) ON DELETE SET NULL,
    UNIQUE (source, external_id)
);
CREATE INDEX ix_coin_news_published ON coin_news (published_at DESC);

INSERT INTO admin_permissions (code, description) VALUES
    ('forum.moderate', 'Forum konularını onaylama, yönetme ve coin haberlerini paylaşma');
INSERT INTO admin_role_permissions (role_code, permission_code) VALUES
    ('super_admin', 'forum.moderate'),
    ('support', 'forum.moderate');
