# Production Dağıtımı

## Gereksinimler
* Docker 24+ ve Docker Compose v2 kurulu bir Linux sunucu (en az 2 vCPU, 4 GB RAM)
* İki alan adı kaydı (A kaydı sunucuya): `panel.` ve `api.`
* Supabase projesi (Pro plan önerilir: günlük yedek ve PITR)
* Anthropic API anahtarı (console.anthropic.com), harcama limiti ayarlanmış olarak

## 1. Supabase
1. Yeni proje oluşturun; bölgeyi kullanıcılarınıza yakın seçin.
2. SQL Editor'da `supabase/migrations/` dosyalarını sırayla çalıştırın (0001, 0002).
3. Authentication > Providers: e-posta açık; "Confirm email" açık.
4. Authentication > URL Configuration: Site URL = `https://panel.ornek.com`.
5. Project Settings > Database > Connection string > **Session pooler** adresini `BC_DATABASE_URL` olarak alın.
6. Database > Backups: günlük yedeklerin ve (varsa) PITR'nin açık olduğunu doğrulayın.

## 2. Ortam değişkenleri
`.env.example` → `.env`. Production'da zorunlu olanlar uygulama açılışında kontrol edilir; eksik veya
güvensiz ayarda backend **başlamaz** ve nedenini listeler:
* `BC_ENVIRONMENT=production`
* `BC_SUPABASE_URL=https://…supabase.co` (JWT'ler JWKS ile doğrulanır)
* `BC_CORS_ORIGINS=["https://panel.ornek.com"]` (localhost veya http yasak)
* `BC_REDIS_URL` (Compose bunu ayarlar)
* `BC_ANTHROPIC_API_KEY`, `BC_MAX_TASK_COST_USD`, `BC_MAX_ACTIVE_TASKS_PER_ORG`
* `PANEL_DOMAIN`, `API_DOMAIN`, `NEXT_PUBLIC_*` (frontend derlemesine gömülür; gizli bilgi koymayın)

## 3. Başlatma
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose ps                       # backend, frontend, worker, beat, redis, caddy: running
curl -fsS https://api.ornek.com/health/ready
```
Caddy sertifikaları otomatik alır ve yeniler. `beat` servisi **tek kopya** çalışmalıdır.
Çalışanı ölçeklemek için: `docker compose up -d --scale worker=3`.

## 4. İzleme
* Sağlık: `GET /health` (süreç), `GET /health/ready` (veritabanı). Bir uptime servisine (ör. dakikada bir) bağlayın.
* Loglar JSON'dur ve her istek `request_id` taşır: `docker compose logs -f backend worker beat`.
* Ajan maliyeti ve hataları: panelde **System Logs** ve **AI Ofis > Canlı akış**.
* Takılı görevler `BC_TASK_TIMEOUT_MINUTES` sonra otomatik "başarısız" olur ve bildirim gönderilir.
* Anthropic Console'da aylık harcama limiti ve uyarısı tanımlayın (uygulama içi görev limitine ek güvenlik).

## 5. Yedekleme ve geri yükleme
* Supabase günlük yedekleri + PITR (Pro plan).
* Ek olarak kendi yedeğiniz: `scripts/backup.sh` (cron örneği betiğin içinde). Yedekleri sunucu dışına kopyalayın.
* Geri yükleme provası (ayda bir önerilir):
  ```bash
  gunzip -c bizcenter-YYYYMMDD.sql.gz | psql "$GERI_YUKLEME_TEST_DB_URL"
  ```

## 6. Güncelleme ve geri alma
```bash
git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# geri alma:
git checkout <önceki-sürüm> && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Yeni migration varsa önce yedek alın, sonra SQL Editor'da çalıştırın.

## 7. Güvenlik kontrol listesi
- [ ] `.env` yalnızca sunucuda, izinleri `600`
- [ ] Supabase service_role anahtarı hiçbir yerde kullanılmıyor (backend kullanıcı JWT'si ve RLS ile çalışır)
- [ ] Anthropic harcama limiti tanımlı
- [ ] Sunucuda yalnızca 22, 80, 443 portları açık
- [ ] İlk kullanıcı kaydından sonra Supabase'de yeni kayıtları kapatmak isteyebilirsiniz (Auth > Providers)
- [ ] Yedek geri yükleme provası yapıldı

## Bilinen sınırlar
* Bağlantılar yalnızca okuma yapar. Video yayınlama, listeleme oluşturma ve fiyat değişikliği gibi yazma işlemleri henüz yok.

## 8. Platform bağlantıları
* **Printify:** Printify > My Profile > Connections > Personal access tokens. İzinler: shops.read, products.read, orders.read, catalog.read. Paneldeki API Integrations sayfasına yapıştırın.
* **Etsy:** developers.etsy.com > Create a New App. Callback URL: `https://panel.ornek.com/integrations/etsy/callback`. Keystring'i `BC_ETSY_KEYSTRING` olarak girin. Etsy uygulamayı onaylayana kadar bağlantı çalışmaz.
* **YouTube:** Google Cloud Console'da proje açın; YouTube Data API v3 ve YouTube Analytics API'yi etkinleştirin. OAuth izin ekranını yapılandırın (test kullanıcısı olarak kendi hesabınızı ekleyin). Web uygulaması OAuth istemcisi oluşturup yönlendirme adresini `https://panel.ornek.com/integrations/youtube/callback` yapın.
* Tüm tokenlar `BC_TOKEN_ENCRYPTION_KEY` ile şifrelenir. Bu anahtar değişirse platformlara yeniden bağlanmak gerekir.
