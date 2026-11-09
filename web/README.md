# web — Web Sitesi ve Müşteri Paneli (Aşama 14)

Next.js 16 (App Router) + TypeScript + Tailwind CSS 4. Herkese açık sayfalar `app/(site)`,
yönetim paneli `app/yonetim` altındadır (Aşama 16).

## Sayfalar

| Yol | İçerik |
|---|---|
| `/` | Ana sayfa |
| `/ozellikler` | Özellikler ve sistem gereksinimleri |
| `/paketler` | Satıştaki paketler (`/v1/plans`); fiyat girilmemişse "yakında" |
| `/satin-al?paket=…` | Paket özeti; ödeme Aşama 17'ye (G3) kadar kapalı |
| `/kayit`, `/giris`, `/eposta-dogrula`, `/sifremi-unuttum`, `/sifre-sifirla` | Hesap akışları |
| `/panel` | Müşteri paneli: lisanslar, cihaz kullanımı, hesap |
| `/sss`, `/iletisim` | Sık sorulan sorular, iletişim formu |
| `/yasal/kullanim-kosullari`, `/yasal/gizlilik`, `/yasal/risk-bildirimi` | Yasal metinler (**taslak, hukukçu onayı bekliyor**) |

## Yönetim paneli (`/yonetim`)

Üretimde yalnızca `ATI_ADMIN_HOST` alan adında (`admin.canarslan.net.tr`) açılır; herkese açık
sitede `/yonetim` 404 döner. Oturum, bulut API'sinin ayrı yönetici çerezindedir (`Path=/admin`,
zorunlu TOTP). Menü role göre süzülür; yetki yalnızca sunucuda denetlenir.

| Yol | İçerik |
|---|---|
| `/yonetim/davet` | Davet: doğrulama uygulaması (QR), parola, kurtarma kodları |
| `/yonetim/giris` | Parola → TOTP veya kurtarma kodu |
| `/yonetim` | Özet |
| `/yonetim/paketler` | Fiyat, para birimi, satışa açma |
| `/yonetim/lisanslar` | Arama, üretim (tekil / toplu CSV), dondurma, iptal, uzatma, tam anahtar (TOTP) |
| `/yonetim/musteriler` | Engelleme, cihaz kaldırma |
| `/yonetim/mesajlar`, `/yonetim/raporlar`, `/yonetim/denetim` | İletişim mesajları, raporlar, denetim kaydı ve zincir doğrulama |
| `/yonetim/yoneticiler` | Davet, engelleme, 2FA sıfırlama |
| `/yonetim/ayarlar` | Ödeme sağlayıcısı ve anahtarları (canlı mod G3 ile), şirket bilgileri, kurtarma kodları |

## Mimari ve güvenlik

* Tarayıcı hesap API'sini (`cloud`, `ati-cloud-api`) doğrudan çağırır. Oturum, API'nin koyduğu
  `HttpOnly; Secure; SameSite=Strict` çerezdedir; JavaScript belirteci görmez. API yalnızca
  `ATI_WEB_ORIGINS` kökenlerinden gelen durum değiştiren istekleri kabul eder (CSRF).
* `proxy.ts` her istekte yeni bir nonce ile CSP üretir: satır içi betik yok, çerçeveleme yasak,
  ağ istekleri yalnızca siteye ve API'ye. Sayfalar bu yüzden dinamik oluşturulur.
* Doğrulama/sıfırlama belirteçleri adres çubuğundan silinir; giriş sonrası yönlendirme yalnızca
  site içi göreli yollara yapılır.
* İçerik kuralı (`lib/content-policy.ts`): hiçbir sayfada kazanç vaadi bulunamaz; her sayfada risk
  uyarısı vardır. Uçtan uca testler tüm sayfa metnini denetler.
* Yalnızca zorunlu oturum çerezi kullanılır; analitik/reklam çerezi yoktur.

## Ortam değişkenleri (çalışma anı)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ATI_PUBLIC_API_URL` | `http://localhost:8000` | Tarayıcının çağırdığı hesap API'si (CSP `connect-src`) |
| `ATI_API_URL` | `ATI_PUBLIC_API_URL` | Sunucunun çağırdığı API (iç ağ adresi olabilir) |
| `ATI_PUBLIC_WEB_URL` | `http://localhost:3000` | Kanonik site adresi (site haritası, meta veriler) |
| `ATI_PLANS_REVALIDATE_S` | `300` | Paket listesi önbellek süresi; `0` önbelleksiz |
| `ATI_ENVIRONMENT` | — | `production` iken HSTS başlığı eklenir |
| `ATI_ADMIN_HOST` | — | Yönetim paneli alan adı; tanımlıysa `/yonetim` yalnızca orada açılır |

## Geliştirme ve testler

```bash
cd web
npm ci
npm run dev                 # http://localhost:3000 (API: cloud/ içinde `uv run ati-cloud-api`)
npm run typecheck && npm test

# Uçtan uca + erişilebilirlik (gerçek PostgreSQL ve bulut API'si gerekir):
export ATI_TEST_DATABASE_URL=postgresql://ati_test:ati_test@127.0.0.1:5432/ati_test
npm run build
npx playwright test         # API'yi boş "ati_e2e" veritabanıyla kendisi başlatır

# Lighthouse (raporlar yalnızca .lighthouseci/reports altına yazılır):
npx lhci autorun            # Chrome yolu gerekirse: CHROME_PATH=/yol/chrome
```

Eşikler (CI): performans ≥ 90, erişilebilirlik = 100, en iyi uygulamalar ≥ 95, SEO ≥ 95. Her sayfa
3 kez ölçülür; eşikler ortanca sonuca uygulanır (sunucu ısınması ve CI dalgalanması tek ölçümü bozmasın).
