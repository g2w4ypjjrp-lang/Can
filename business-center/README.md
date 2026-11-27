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

## Phase 2 (AI Core)

* CEO Komut Merkezi: doğal dilde komut. CEO planlar, uzman ajanlara dağıtır, kalite kontrol ekler ve tek rapor sunar
* Görev Yönetimi: adım adım canlı ilerleme, ajan çıktıları, kaynaklar, iptal
* System Logs: her ajan çağrısının token kullanımı ve maliyeti
* Görev başına harcama üst sınırı ve eşzamanlı görev sınırı
* Celery + Redis çalışanı (Docker Compose içinde `worker`)

**Henüz yok:** Gerçek Claude çağrısı için `BC_ANTHROPIC_API_KEY` gerekli. Anahtar yoksa görevler
"API anahtarı yapılandırılmadı" hatasıyla durur. YouTube, Etsy ve Printify bağlantıları Phase 3 ve 4'te gelecek. Panelde bu bölümler
"Phase N" etiketiyle açıkça işaretli.

## Phase 5-6 ve Finans

* Kalite kontrol döngüsü: kalırsa bir kez düzeltme, sonuç her durumda raporlanır, telif riskinde insan incelemesi
* Automation: 10 hazır şablon (günlük, haftalık, aylık), özel cron kuralları, varsayılan kapalı
* Notifications: görev bitti/başarısız, atlanan otomasyon
* Financial Reports: YouTube, Etsy ve birleşik kâr-zarar, manuel kayıt, eksik veri uyarıları, doğrulanmış rapor

## Kurulum

### 1. Supabase
1. [supabase.com](https://supabase.com) üzerinde bir proje oluşturun.
2. SQL Editor'da `supabase/migrations/` içindeki dosyaları sırayla (0001, 0002) çalıştırın.
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
