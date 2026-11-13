-- Yeni coin haberinden otomatik konu taslağı: haber "drafted" olur ve taslak konuya bağlanır;
-- taslak forum onay kuyruğuna düşer. Yönetici onaylayınca haber "shared", reddedince "dismissed".
ALTER TABLE coin_news DROP CONSTRAINT coin_news_status_check;
ALTER TABLE coin_news ADD CONSTRAINT coin_news_status_check
    CHECK (status IN ('new', 'drafted', 'shared', 'dismissed'));
CREATE INDEX ix_coin_news_topic ON coin_news (topic_id) WHERE topic_id IS NOT NULL;
