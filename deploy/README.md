# Üretim yapılandırması — canarslan.net.tr

> **Adım adım yayına alma — iki seçenek:**
>
> * **Kendi Windows sunucunuz (VDS), ek ücret yok:** [`windows-sunucu/README.md`](windows-sunucu/README.md)
>   (tek betik: `windows-sunucu/kur.ps1`). İşlem motoru sunucuya kurulmaz.
> * **Render (yönetilen, ücretli) + Cloudflare:** [`render.md`](render.md),
>   [`../render.yaml`](../render.yaml).

Alan adı belirlendi: **`canarslan.net.tr`**. Bulut sağlayıcısı, bölge ve üretime dağıtım **G5
onayı** ile yapılacaktır; bu klasör o güne kadar hedef yapıyı ve gizli bilgi içermeyen ayar
örneklerini tutar.

## Adresler

| Adres | Hizmet | Kaynak |
|---|---|---|
| `https://canarslan.net.tr` | Web sitesi ve müşteri paneli | `web/` (`next start`) |
| `https://www.canarslan.net.tr` | Kalıcı yönlendirme (301) → `https://canarslan.net.tr` | yük dengeleyici |
| `https://api.canarslan.net.tr` | Hesap, lisans ve (Aşama 17) ödeme API'si | `cloud/` (`ati-cloud-api`) |
| `wss://relay.canarslan.net.tr` | iPhone ↔ masaüstü aktarma servisi | `cloud/` (`ati-cloud-relay`) |
| `https://admin.canarslan.net.tr` | Admin paneli (Aşama 16): paketler, fiyatlar, ödeme ayarları, lisanslar, sürümler | `web/` (`/yonetim`, `ATI_ADMIN_HOST`) |
| `https://indir.canarslan.net.tr` | Windows kurulum paketleri (yalnızca statik dosya) | nesne deposu + CDN |

E-posta (sağlayıcı seçilince): gönderen `bildirim@canarslan.net.tr`, destek `destek@canarslan.net.tr`.

## Kapsayıcı imajları

VDS kullanılmaz; servisler yönetilen bir kapsayıcı platformunda çalışır. İki imaj vardır, ikisi de
ortamdan bağımsızdır (ayarlar çalışma anında ortam değişkeniyle verilir), gizli bilgi içermez ve
root olmayan kullanıcıyla çalışır. CI (`containers` işi) her gönderimde ikisini derler, yalnızca
üretim bağımlılıklarıyla açılıp açılmadığını ve sayfaların yanıt verdiğini dener.

| İmaj | Derleme | Süreçler |
|---|---|---|
| `ati-web` | `docker build -t ati-web web/` | site + müşteri paneli + yönetim paneli, port 3000 |
| `ati-cloud` | `docker build -t ati-cloud cloud/` | `ati-cloud-api` (8000, varsayılan), `ati-cloud-relay` (8765), `ati-cloud-migrate` (dağıtım öncesi tek sefer), `ati-cloud-payments maintain` (10 dk'da bir) |

Platformda dikkat edilecekler:

* **Aktarma servisi tek örnek çalışmalı.** Motor ile telefon aynı süreçte buluşur (bellek içi
  yönlendirme); en fazla 1 örnek ve WebSocket desteği gerekir. Bağlantı koparsa motor ve telefon
  kendiliğinden yeniden bağlanır.
* API ve site yatay ölçeklenebilir (durum veritabanında). Sağlık denetimi: API `/ready`, aktarma
  `/health`, site `/robots.txt`.
* Her dağıtımda önce `ati-cloud-migrate` çalıştırılır; API `/ready` bekleyen geçiş varsa 503 döner.

## İndirme dosyaları (indir.canarslan.net.tr)

1. GitHub'da **Actions → Masaüstü → Run workflow** ile elle başlatılan **Windows kurulum paketi**
   işi imzasız `*-setup.exe` dosyasını, yanında
   `.sha256` dosyasıyla üretir; iş özetinde sürüm, boyut (bayt) ve SHA-256 yazar.
2. Dosya, sürüm numaralı ve **değişmeyen** bir adla indirme deposuna yüklenir (ör.
   `AI-Trading-Intelligence_0.14.4_x64-setup.exe`). Aynı ada farklı dosya yüklenmez; yeni sürüm yeni
   addır. Depo herkese açık okunur, yazma yetkisi yalnızca dağıtımı yapan kişidedir.
3. Yönetim paneli → **Sürümler**: adres, SHA-256 ve boyut girilerek taslak eklenir, kontrol edilir ve
   doğrulama kodu (TOTP) ile yayınlanır. Site İndir sayfasında en son yayındaki sürümü gösterir.
   Yayınlanan sürümün adresi/özeti değiştirilemez; hatalıysa geri çekilir ve yeni sürüm eklenir.
4. Kod imzalama (G6) gelene kadar sayfa “imzasız” uyarısını ve PowerShell ile özet doğrulama
   komutunu gösterir.

Bağlantı yalnızca `ATI_RELEASE_DOWNLOAD_HOSTS` alan adlarına verilebilir; yönetici oturumu ele
geçirilse bile müşteriler başka bir siteye yönlendirilemez.

## Neden bu yapı

* `canarslan.net.tr` ile `api.canarslan.net.tr` **aynı sitedir** (`net.tr` genel sonektir). Bu
  yüzden API'nin oturum çerezi `SameSite=Strict` ile web sitesinden yapılan isteklerde gönderilir;
  başka sitelerden gönderilmez. Çerezde `Domain` belirtilmez (yalnızca `api.` alt alan adına ait).
* Admin paneli ayrı alt alan adında, ayrı oturum tablosu ve zorunlu 2FA ile çalışır; müşteri
  oturumu admin paneline erişemez.
* Aktarma servisi ayrı süreçtir ve anahtar tutmaz; ele geçirilse bile komut üretemez.

## İlk yönetici

Yayına almadan sonra ilk süper yönetici sunucudan davet edilir; bağlantıyı açan kişi parolasını
ve doğrulama uygulamasını (TOTP) kurar, 10 kurtarma kodunu kaydeder:

```bash
uv run ati-cloud-admin invite --email <yönetici e-postası> --name "<Ad Soyad>"
```

Diğer yöneticiler panelden (Yöneticiler) davet edilir. Gizli değer `ATI_ADMIN_SECRET_KEK`
(TOTP sırları ve ödeme anahtarları) gizli bilgi deposundan verilir.

## DNS ve TLS kontrol listesi (G5 sırasında)

* [ ] `canarslan.net.tr`, `www`, `api`, `relay`, `admin`, `indir` kayıtları (sağlayıcının yük dengeleyicisine / CDN'e)
* [ ] `CAA` kaydı: yalnızca kullanılan sertifika otoritesi
* [ ] TLS 1.2+ (tercihen 1.3), otomatik yenilenen sertifikalar
* [ ] HSTS (`max-age=63072000; includeSubDomains; preload`) — site üretimde zaten gönderir
  (`ATI_ENVIRONMENT=production`). **Preload listesine başvuru geri alınması zor bir adımdır;**
  tüm alt alan adları HTTPS çalıştıktan sonra yapılmalı.
* [ ] E-posta: `SPF`, `DKIM`, `DMARC` (`p=quarantine` ile başlayıp `reject`'e geçilir)
* [ ] Veritabanı: yönetilen PostgreSQL 16, `sslmode=verify-full`, şifreli yedek ve geri yükleme tatbikatı

## Ayar örnekleri

* [`web.env.example`](web.env.example) — web sitesi
* [`cloud.env.example`](cloud.env.example) — hesap API'si ve aktarma servisi

Gizli değerler (veritabanı parolası, lisans imza anahtarı, ödeme sağlayıcı anahtarları) bu
dosyalara **yazılmaz**; bulut sağlayıcısının gizli bilgi deposundan ortam değişkeni olarak verilir.
Ödeme sağlayıcı anahtarları admin panelinden (Ayarlar → Ödeme) şifreli olarak girilir.

**Ödeme (Aşama 17):**

* PayTR mağaza panelinde bildirim adresi: `https://api.canarslan.net.tr/v1/payments/webhooks/paytr`.
* iyzico ödeme formu dönüş adresi otomatik verilir: `https://api.canarslan.net.tr/v1/payments/return/iyzico`.
* Zamanlanmış görev (ör. 10 dakikada bir): `ati-cloud-payments maintain` — tarayıcısı geri
  dönmeyen iyzico ödemelerini sorgular, 24 saati geçen ödenmemiş siparişleri iptal eder.
* Üretimde test modunda satış açılmaz; canlı ödeme `ATI_PAYMENTS_LIVE_ALLOWED=true` (G3) ve
  panelde canlı mod gerektirir.

## Yedekleme ve felaket kurtarma (G5 sırasında ayarlanır)

* Yönetilen PostgreSQL'de otomatik günlük yedek + zaman noktasına geri dönüş (PITR) açılır;
  en az 30 gün saklanır ve başka bir bölgeye kopyalanır.
* Gizli bilgiler (`ATI_LICENSE_KEK`, `ATI_LICENSE_PEPPER`, `ATI_LEASE_SIGNING_KEY`,
  `ATI_ADMIN_SECRET_KEK`) yedeklerden **ayrı** gizli bilgi deposunda tutulur. Yedek bu anahtarlar
  olmadan lisans anahtarlarını açamaz; anahtarlar kaybedilirse yedek de işe yaramaz. İkisi de
  ayrı ayrı korunmalıdır.
* Geri yükleme adımları `cloud/scripts/dr_drill.py`'deki tatbikatla aynıdır: `pg_restore` →
  `ati-cloud-migrate --check` → aynı gizli bilgilerle API'yi başlat → `/ready` → lisans kira
  yenileme ve denetim zinciri doğrulaması (`audit_log_verify()`). Tatbikat CI'da her gönderimde
  çalışır; canlı ortamda üç ayda bir gerçek yedekle tekrarlanmalı.
* Ödeme bakımı için zamanlanmış görev: `ati-cloud-payments maintain` (10 dakikada bir).

## Masaüstü ve iPhone

Masaüstü motorunun aktarma adresi (`remote.relay_url`) aktarma servisi yayına alındığında
`wss://relay.canarslan.net.tr` olarak sürüm ayarlarına eklenecek. O zamana kadar telefon
eşleştirmesi kapalıdır (motor, aktarma adresi yokken eşleştirme isteğini G5 gerekçesiyle reddeder).
