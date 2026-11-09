# Üretim yapılandırması — canarslan.net.tr

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
| `https://admin.canarslan.net.tr` | Admin paneli (Aşama 16): paketler, fiyatlar, ödeme ayarları, lisanslar | `web/` (`/yonetim`, `ATI_ADMIN_HOST`) |

E-posta (sağlayıcı seçilince): gönderen `bildirim@canarslan.net.tr`, destek `destek@canarslan.net.tr`.

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

* [ ] `canarslan.net.tr`, `www`, `api`, `relay`, `admin` kayıtları (sağlayıcının yük dengeleyicisine)
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

## Masaüstü ve iPhone

Masaüstü motorunun aktarma adresi (`remote.relay_url`) aktarma servisi yayına alındığında
`wss://relay.canarslan.net.tr` olarak sürüm ayarlarına eklenecek. O zamana kadar telefon
eşleştirmesi kapalıdır (motor, aktarma adresi yokken eşleştirme isteğini G5 gerekçesiyle reddeder).
