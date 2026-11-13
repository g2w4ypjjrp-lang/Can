-- Haberlerin Türkçe çevirisi (başlık ve kısa özet; haberin tamamı kaynağındadır).
ALTER TABLE coin_news ADD COLUMN lang text NOT NULL DEFAULT 'tr' CHECK (lang ~ '^[a-z]{2}$');
ALTER TABLE coin_news ADD COLUMN title_tr text CHECK (length(title_tr) <= 400);
ALTER TABLE coin_news ADD COLUMN summary_tr text CHECK (length(summary_tr) <= 800);
