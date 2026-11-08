-- Aşama 14: web sitesi iletişim formu. Mesajlar yönetici panelinde (Aşama 16) yanıtlanır.
-- Saklama süresi gizlilik politikasında belirtilir; süresi dolanlar zamanlanmış görevle silinir.

CREATE TABLE contact_messages (
    id          bigserial PRIMARY KEY,
    customer_id uuid REFERENCES customers (id) ON DELETE SET NULL,
    name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    email       citext NOT NULL CHECK (length(email) <= 254),
    topic       text NOT NULL CHECK (topic IN ('sales', 'support', 'license', 'privacy', 'other')),
    message     text NOT NULL CHECK (length(message) BETWEEN 10 AND 5000),
    ip          inet,
    user_agent  text CHECK (length(user_agent) <= 300),
    status      text NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'in_progress', 'closed', 'spam')),
    handled_by  uuid REFERENCES admin_users (id),
    handled_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX contact_messages_status_idx ON contact_messages (status, created_at DESC);
CREATE INDEX contact_messages_email_idx ON contact_messages (email);
