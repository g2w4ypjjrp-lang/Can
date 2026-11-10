# ati-cloud — Lisans, Hesap, Ödeme ve Aktarma Servisi

Yönetilen bulut altyapısında (kiralık VDS değil) çalışan FastAPI servisi. İşlem motoru
**burada çalışmaz**; motor kullanıcının Windows bilgisayarındadır. Bu servis yalnızca
hesapları, lisansları, cihaz aktivasyonlarını, ödemeleri ve iOS ↔ masaüstü aktarmasını
yönetir. Mimari: [`../docs/01-sistem-mimarisi.md`](../docs/01-sistem-mimarisi.md),
şema: [`../docs/04-veritabani-semasi.md`](../docs/04-veritabani-semasi.md).

## Geliştirme

```bash
cd cloud
uv sync
# Testler gerçek bir PostgreSQL 16 ister:
export ATI_TEST_DATABASE_URL=postgresql://ati_test:ati_test@127.0.0.1:5432/ati_test
uv run pytest
uv run ruff check . && uv run mypy
```

## Hesap API'si (Aşama 14)

```bash
export ATI_DATABASE_URL=postgresql://...
uv run ati-cloud-api --host 127.0.0.1 --port 8000   # TLS sonlandıran yük dengeleyicinin arkasında
```

| Uç nokta | Açıklama |
|---|---|
| `GET /v1/plans` | Satıştaki paketler (fiyatı girilmiş ve etkin) |
| `POST /v1/auth/register` | Kayıt; adres kayıtlıysa da aynı yanıt (hesap sızdırmaz) |
| `POST /v1/auth/verify-email`, `POST /v1/auth/resend-verification` | E-posta doğrulama |
| `POST /v1/auth/login`, `POST /v1/auth/logout` | Oturum (`ati_session` çerezi) |
| `POST /v1/auth/password-reset`, `POST /v1/auth/password-reset/confirm` | Parola sıfırlama; tüm oturumları kapatır |
| `GET /v1/me` | Müşteri paneli: profil, lisanslar, etkin cihaz sayısı |
| `POST /v1/contact` | İletişim formu |

Ayarlar (`ATI_` önekli): `WEB_ORIGINS` (CSRF için izinli kökenler), `PUBLIC_WEB_URL`
(e-posta bağlantıları), `SESSION_COOKIE_SECURE` (staging/üretimde zorunlu `true`),
`SESSION_DAYS`, `TRUSTED_PROXIES` (`X-Forwarded-For`'a güvenilen vekiller). E-postalar
`email_outbox` tablosuna yazılır; gönderim, e-posta sağlayıcısı seçilince (G5).

## Lisans sistemi (Aşama 15)

Protokol: [`../shared/protocol/license-v1.md`](../shared/protocol/license-v1.md).

```bash
uv run ati-cloud-license gen-secrets      # pepper, KEK ve kira imza anahtarı (gizli bilgi deposuna)
uv run ati-cloud-license public-key       # motor sürümüne gömülecek kira açık anahtarı
uv run ati-cloud-license issue --plan d30_1dev --email musteri@ornek.com   # elle satış
```

Gizli değerler: `ATI_LICENSE_PEPPER`, `ATI_LICENSE_KEK` (+ `ATI_LICENSE_KEK_ID`),
`ATI_LEASE_SIGNING_KEY`; staging/üretimde zorunlu. Yoksa lisans uç noktaları 503 döner.

| Uç nokta | Kimlik | Açıklama |
|---|---|---|
| `POST /v1/licenses/activate` / `renew` / `deactivate` | Cihazın imzalı isteği | Motor: etkinleştirme, kira yenileme, bilgisayarı bırakma |
| `GET /v1/licenses/signing-key` | — | Kira imza açık anahtarı |
| `POST /v1/me/licenses/{id}/devices/{device_id}/deactivate` | Oturum + köken | Müşteri: bilgisayar kaldırma (30 günde 3) |
| `POST /v1/me/licenses/{id}/reveal` | Oturum + köken + parola | Müşteri: tam anahtar |

Test vektörleri `scripts/gen_license_vectors.py` ile üretilir; motor bunlarla doğrular.

## Yönetici API'si (Aşama 16)

`/admin/v1` — müşteri hesaplarından ayrı giriş (davet → parola + TOTP, kurtarma kodları), ayrı
çerez (`ati_admin`, `Path=/admin`), rol bazlı yetki (her uç nokta tek yetki; `tests/test_admin_rbac.py`
tüm rotaları her rolle dener). İlk süper yönetici:

```bash
uv run ati-cloud-admin invite --email yonetici@canarslan.net.tr --name "Ad Soyad"
```

Ayarlar: `ATI_ADMIN_ORIGINS`, `ATI_ADMIN_PUBLIC_URL` (davet bağlantıları), `ATI_ADMIN_SESSION_HOURS`
(en fazla 12), `ATI_ADMIN_SECRET_KEK` (gizli; TOTP sırları ve ödeme anahtarları),
`ATI_PAYMENTS_LIVE_ALLOWED` (canlı ödeme; yalnızca G3 onayıyla `true`).

## Ödeme ve lisans teslimi (Aşama 17)

Sağlayıcı (PayTR, iyzico; geliştirme/testte simülatör) ve anahtarları admin panelinden seçilir
(Ayarlar → Ödeme). Akış ve güvenlik kuralları: [`docs/04`](../docs/04-veritabani-semasi.md) §1.4,
`src/ati_cloud/payments/service.py`.

| Uç nokta | Kimlik | Açıklama |
|---|---|---|
| `GET /v1/payments/status` | — | Satış açık mı, test modu mu |
| `GET /v1/legal/seller` | — | Satıcı bilgileri (yasal metinler) |
| `POST /v1/checkout` | Oturum + köken | Sipariş + sağlayıcının ödeme sayfası |
| `GET /v1/me/orders`, `/v1/me/orders/{no}` | Oturum | Siparişler, sonuç sayfası |
| `POST /v1/payments/webhooks/paytr` | İmza (HMAC) | PayTR bildirimi; yanıt `OK` |
| `POST /v1/payments/return/iyzico` | Sağlayıcıya imzalı sorgu | Tarayıcı dönüşü → sonuç sayfası |
| `GET/POST /v1/payments/simulator/*` | Oturum (yalnızca geliştirme/test) | Test ödemesi |
| `GET /admin/v1/orders/{id}`, `POST …/refund`, `POST …/reconcile` | Yönetici (`order.read`, `payment.refund` + TOTP, `payment.read`) | Ayrıntı, iade, sağlayıcı sorgusu |

```bash
uv run ati-cloud-payments maintain --reconcile-minutes 10 --expire-hours 24   # zamanlanmış görev
```

Ayarlar: `ATI_PUBLIC_API_URL` (sağlayıcının dönüş/bildirim adresi; üretimde HTTPS). Üretimde test
modunda satış açılmaz; canlı ödeme `ATI_PAYMENTS_LIVE_ALLOWED=true` (G3) ve panelde canlı mod ister.

## Güvenlik, yük ve felaket kurtarma (Aşama 18)

* **İstek koruması** (`src/ati_cloud/guards.py`): uygulama gövdeyi ayrıştırmadan önce köken
  (CSRF), 256 KB gövde sınırı, UTF-8 ve JSON derinliği denetlenir.
* **Sızma testi tarzı testler** (`tests/test_pentest.py`): her rota bir güvenlik sınıfına
  atanmak zorundadır; IDOR, enjeksiyon, toplu atama, CORS, çerez bayrakları.
* **Yük testi** (gerçek sunucular, PostgreSQL; CI'da `--quick`):

  ```bash
  uv run python scripts/load_test.py --engines 200 --renewals 5 --concurrency 50
  ```

* **Felaket kurtarma tatbikatı** (`pg_dump` → `pg_restore` → iş sürekliliği; CI'da her gönderimde):

  ```bash
  uv run python scripts/dr_drill.py
  ```

* `ATI_DATABASE_POOL_MAX`: süreç başına bağlantı havuzu (varsayılan 10).

## Geçişler (migrations)

```bash
export ATI_DATABASE_URL=postgresql://...
uv run ati-cloud-migrate          # bekleyen geçişleri uygular
uv run ati-cloud-migrate --check  # yalnızca durumu raporlar
```

Geçişler `src/ati_cloud/db/migrations/NNNN_ad.sql` dosyalarıdır. Uygulanmış bir geçiş
dosyası değiştirilirse (özet uyuşmazlığı) çalıştırıcı hata verir. Aynı anda birden fazla
örnek açılırsa PostgreSQL advisory lock ile yalnızca biri geçiş uygular.

## Aktarma servisi (Aşama 13)

iOS ↔ masaüstü motoru arasında uçtan uca imzalı mesajları yönlendirir
([protokol](../shared/protocol/remote-v1.md)). Servis hiçbir anahtar tutmaz ve içerikleri
yorumlamaz. Ele geçirilse bile komut üretemez, durum sahteleyemez, cihaz eşleştiremez.
Ayrı bir süreç olarak çalışır:

```bash
uv run ati-cloud-relay --host 0.0.0.0 --port 8765   # TLS (wss://) önündeki yük dengeleyicide
```

Uç noktalar `/v1/relay/engine` ve `/v1/relay/device`. Bağlanan taraf kimliğini imzalı `hello`
ile kanıtlar. Hız sınırı ve motor başına 20 telefon sınırı vardır. Tek örnek durumu bellektedir;
birden çok örnek için Redis pub/sub dağıtım aşamasında (G5) eklenecek.
