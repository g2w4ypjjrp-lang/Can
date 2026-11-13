-- Forum: kalıcı üye adı (profil ve rütbe için), beğeniler ve coin konularında yükseliş/düşüş oyu.

CREATE TABLE forum_profiles (
    customer_id  uuid PRIMARY KEY REFERENCES customers (id) ON DELETE CASCADE,
    nickname     citext NOT NULL UNIQUE CHECK (length(nickname) BETWEEN 2 AND 40),
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Beğeni: konu ya da yanıt (hedef silinirse sayımda görünmez; moderasyon silmesinde temizlenir).
CREATE TABLE forum_likes (
    customer_id  uuid NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    target_type  text NOT NULL CHECK (target_type IN ('topic', 'reply')),
    target_id    uuid NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, target_type, target_id)
);
CREATE INDEX ix_forum_likes_target ON forum_likes (target_type, target_id);

CREATE TABLE forum_sentiment (
    topic_id     uuid NOT NULL REFERENCES forum_topics (id) ON DELETE CASCADE,
    customer_id  uuid NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    vote         text NOT NULL CHECK (vote IN ('bull', 'bear')),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (topic_id, customer_id)
);

-- Var olan müşteri gönderilerinden profil: müşterinin en son kullandığı ad (çakışmada atlanır).
INSERT INTO forum_profiles (customer_id, nickname, created_at)
SELECT DISTINCT ON (customer_id) customer_id, author_name, created_at
FROM (
    SELECT customer_id, author_name, created_at FROM forum_topics
    WHERE customer_id IS NOT NULL AND author_kind = 'customer'
    UNION ALL
    SELECT customer_id, author_name, created_at FROM forum_replies
    WHERE customer_id IS NOT NULL AND author_kind = 'customer'
) x
ORDER BY customer_id, created_at DESC
ON CONFLICT DO NOTHING;
