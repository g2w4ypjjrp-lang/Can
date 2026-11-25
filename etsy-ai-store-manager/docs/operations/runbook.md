# Operasyon el kitabı

## Migration

- Yeni değişiklik = **yeni dosya** (`packages/database/supabase/migrations/<zaman>_<ad>.sql`). Uygulanmış bir
  migration'ı düzenlemek yasaktır; çalıştırıcı SHA-256 ile tespit edip durur.
- Her yeni tabloda RLS açılmalı; entegrasyon testi RLS'siz tablo bulursa başarısız olur.

## Yedekleme

- `infrastructure/scripts/backup.sh` — `pg_dump` (custom format) + GPG AES-256 şifreleme + SHA-256 + 14 gün saklama.
- Cron: `17 3 * * * cd /opt/esm/etsy-ai-store-manager && set -a && . ./.env && ./infrastructure/scripts/backup.sh >> backups/backup.log 2>&1`
- Yedekleri sunucu dışına kopyalayın (ör. ayrı bir object storage). Supabase'in kendi yedekleri/PITR'si ayrıca vardır.
- Geri yükleme testi ayda bir: `TARGET_DATABASE_URL=<boş db> ./infrastructure/scripts/restore.sh backups/<dosya>`

## Loglama ve izleme

- API/worker JSON log (pino); her istekte `x-request-id` (Nginx'ten iletilir, audit kaydına yazılır).
  Authorization/cookie/token alanları maskelenir.
- Sağlık: `GET /api/v1/health` (liveness), `GET /api/v1/health/ready` (DB + Redis). Docker healthcheck'leri tanımlı.
- Worker: `automation_jobs` tablosunda her işin durumu, deneme sayısı ve son hatası. Başarısız işler:
  `select job_name, last_error, attempts from automation_jobs where status='failed' order by created_at desc;`
- Dış API çağrıları (FAZ 2+) `api_logs` tablosuna yazılır (gövde/belirteç asla saklanmaz).

## Anahtar rotasyonu (TOKEN_ENCRYPTION_KEY)

Şifreli zarf anahtar sürümünü taşır (`v<n>.`). Rotasyon: yeni anahtarı yeni sürümle ekle → worker işi ile
tüm belirteçleri yeniden şifrele → eski anahtarı kaldır. (Çoklu anahtar yükleme FAZ 2'de eklenecek.)

## Olay müdahalesi

1. Şüpheli erişim: Supabase'te ilgili kullanıcının oturumlarını iptal edin, `audit_logs`'u inceleyin.
2. Belirteç sızıntısı şüphesi: Etsy/Printify'da uygulama erişimini iptal edin, `connected_accounts.status='revoked'`.
