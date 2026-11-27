# AI Business Center

YouTube kanalınızı ve mevcut Etsy + Printify işletmenizi tek panelden yöneten, uzman AI
ajanlarıyla çalışan ve kritik işlemleri onayınıza sunan platform.

Mimari ve yol haritası: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Şu an çalışan (Phase 1)

* Supabase şeması: 36 tablo, foreign key, index, zaman damgaları, RLS
* Giriş ve kayıt (Supabase Auth), işletme oluşturma, 21 ajanın otomatik kurulumu
* Dashboard: gerçek veriden hesaplanır. Veri yoksa "Bağlı değil" veya "Henüz veri yok" gösterilir, sayı uydurulmaz
* AI Employees sayfası
* Approval Center: onay ve ret, ret nedeni zorunlu, süre aşımı, geçmiş ve denetim kaydı
* Güvenlik: JWT doğrulama, RLS, rate limit, güvenlik başlıkları, yalnızca eklemeye açık denetim kaydı
* Docker Compose ve CI iş akışı

**Henüz yok:** Ajanlar şu an çalışmıyor; Claude API bağlantısı Phase 2'de gelecek. YouTube,
Etsy ve Printify bağlantıları da yok, Phase 3 ve 4'te gelecek. Panelde bu bölümler
"Phase N" etiketiyle açıkça işaretli.

## Kurulum

### 1. Supabase
1. [supabase.com](https://supabase.com) üzerinde bir proje oluşturun.
2. SQL Editor'da `supabase/migrations/0001_core.sql` dosyasını çalıştırın.
3. `.env.example` dosyasını `.env` olarak kopyalayın ve değerleri doldurun.
4. Frontend için aynı `NEXT_PUBLIC_*` değerlerini `frontend/.env.local` dosyasına yazın.

### 2. Çalıştırma
```bash
docker compose up --build        # http://localhost:3000
```
Docker olmadan:
```bash
cd backend && uv sync && uv run bizcenter-api
cd frontend && npm install && npm run dev
```

### 3. Testler
```bash
./scripts/test.sh
```
Backend testleri gerçek bir PostgreSQL 16 ister. Bağlantıyı `BC_TEST_ADMIN_DSN` ile verin.
