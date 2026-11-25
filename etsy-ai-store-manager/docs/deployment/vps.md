# VPS'e production kurulumu

Önkoşullar: Ubuntu 24.04 VPS (2 vCPU / 4 GB RAM yeterli), alan adı (A kaydı VPS IP'sine), Docker + Compose, bir Supabase projesi.

## 1. Supabase

1. Yeni proje oluşturun. **Authentication → URL Configuration**: Site URL `https://alanadiniz`, Redirect URL `https://alanadiniz/auth/callback`.
2. Migration'ları uygulayın (yerel makinede):
   ```bash
   npx supabase@2 link --workdir packages/database --project-ref <ref>
   npx supabase@2 db push --workdir packages/database
   ```
   Alternatif: `docker compose --profile migrate run --rm migrate` (DATABASE_URL ile).
3. `.env` için: Project URL, publishable/anon key, pooler bağlantı dizesi (port 6543, `sslmode=require`).

## 2. Sunucu

```bash
git clone <repo> /opt/esm && cd /opt/esm/etsy-ai-store-manager
cp .env.example .env && chmod 600 .env   # değerleri doldurun
openssl rand -base64 32                  # TOKEN_ENCRYPTION_KEY
sed -i 's/example.com/alanadiniz.com/g' infrastructure/nginx/conf.d/app.conf
```

## 3. HTTPS sertifikası

İlk sertifika için 443 bloğunu geçici olarak yorum satırı yapıp yalnızca 80'i başlatın:

```bash
docker compose up -d nginx
docker compose --profile certbot run --rm certbot certonly --webroot -w /var/www/certbot -d alanadiniz.com --email siz@ornek.com --agree-tos
# 443 bloğunu geri açın
docker compose up -d --build
```

Yenileme (cron): `0 4 * * 1 cd /opt/esm/etsy-ai-store-manager && docker compose --profile certbot run --rm certbot renew && docker compose exec nginx nginx -s reload`

## 4. Doğrulama

```bash
curl -fsS https://alanadiniz.com/api/v1/health/ready   # {"status":"ready",...}
docker compose ps
docker compose logs -f api worker
```

## 5. Güvenlik kontrol listesi

- `.env` izinleri 600, Git'e eklenmez (`.gitignore`).
- `SWAGGER_ENABLED=false` veya Nginx'te `/docs` yalnızca kendi IP'nize açık.
- UFW: yalnızca 22, 80, 443. SSH parola girişi kapalı.
- Yedekleme cron'u (bkz. `docs/operations/runbook.md`).
