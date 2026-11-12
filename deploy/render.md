# canarslan.net.tr'yi yayına alma — Render + Cloudflare (adım adım)

Bu rehber, alan adı **Cloudflare**'de olan `canarslan.net.tr` için hazırlandı. Uygulama sunucuları
**Render** (Frankfurt) üzerinde, depodaki [`render.yaml`](../render.yaml) ile tek seferde kurulur.
VDS kullanılmaz. Kurulum dosyası Render'ın resmi şemasıyla doğrulanmıştır ve aynı ayarlar üretim
kipinde yerel olarak denenmiştir (veritabanı TLS 1.3, admin yalnızca kendi alan adında, istemci
adresi doğru).

Kurulacaklar:

| Ad | Ne | Adres |
|---|---|---|
| `ati-web` | Site, müşteri paneli, yönetim paneli | `canarslan.net.tr`, `www.` (yönlendirme), `admin.canarslan.net.tr` |
| `ati-api` | Hesap, lisans, ödeme, yönetim API'si | `api.canarslan.net.tr` |
| `ati-relay` | iPhone ↔ bilgisayar aktarma | `relay.canarslan.net.tr` |
| `ati-odeme-bakimi` | 10 dakikada bir ödeme bakımı | — |
| `ati-db` | PostgreSQL 16 (dışarıdan erişime kapalı) | — |
| Cloudflare R2 | Windows kurulum dosyaları | `indir.canarslan.net.tr` |

> Veriler Frankfurt'ta (AB) tutulur. Yurt dışına veri aktarımı için KVKK değerlendirmesini
> hukukçunuzla yapın. Canlı ödeme kapalıdır; açmak ayrı onay (G3) ister.

## 1. Render hesabı (siz)

1. <https://render.com> → **Get Started** → **GitHub ile giriş**.
2. Render'ın GitHub erişimi sorulduğunda `g2w4ypjjrp-lang/Can` deposuna izin verin.
3. **Billing** bölümünden ödeme yöntemi ekleyin (sunucular ücretlidir; ücretsiz planda veritabanı
   geçişleri ve konsol çalışmaz). Planların ücretleri <https://render.com/pricing> sayfasındadır.

## 2. Blueprint ile kurulum (siz, 2 dakika)

1. Render panelinde **New → Blueprint**.
2. `g2w4ypjjrp-lang/Can` deposunu seçin.
3. **Branch:** şimdilik `claude/laughing-hawking-wmt8mo` (en güncel, test edilmiş kod). GitHub
   Actions düzelip testler geçince `ana` dalına alınacak.
4. Blueprint adı: `canarslan`. Listede 4 servis + 1 veritabanı görünür → **Deploy Blueprint**.
5. İlk derleme 5-10 dakika sürer. `ati-api`, `ati-relay`, `ati-web` yeşil (**Live**) olmalı.
   Bir servis dağıtılmadıysa: servise girin → **Manual Deploy → Deploy latest commit**.

Otomatik güncelleme yalnızca GitHub testleri geçtiğinde yapılır (`checksPass`). Actions şu an
çalışmadığı için yeni sürümler elle dağıtılır (Manual Deploy).

## 3. Gizli anahtarları yedekleyin (siz, önemli)

Render, lisans ve yönetici anahtarlarını kendisi üretti. **Environment Groups → `ati-gizli`**
içindeki 4 değeri (`ATI_LICENSE_PEPPER`, `ATI_LICENSE_KEK`, `ATI_LEASE_SIGNING_KEY`,
`ATI_ADMIN_SECRET_KEK`) bir parola yöneticisine kaydedin. Bu değerleri kimseyle (sohbet dahil)
paylaşmayın. Kaybolursa veritabanı yedeğindeki lisans anahtarları açılamaz; değiştirilirse
mevcut lisanslar ve yönetici doğrulama kodları çalışmaz.

## 4. Cloudflare DNS (siz)

Cloudflare panelinde `canarslan.net.tr` → **DNS → Records**:

1. `@`, `www`, `admin`, `api`, `relay` adlarında mevcut **A / AAAA** kayıtları varsa silin
   (Render IPv6 desteklemez).
2. Render'da her servisin **Settings → Custom Domains** bölümünde hedef adres yazar
   (`ati-web-xxxx.onrender.com` gibi). Şu **CNAME** kayıtlarını ekleyin, hepsinde
   **Proxy status: DNS only** (gri bulut):

| Ad | Hedef |
|---|---|
| `@` | `ati-web` hedef adresi |
| `www` | `ati-web` hedef adresi |
| `admin` | `ati-web` hedef adresi |
| `api` | `ati-api` hedef adresi |
| `relay` | `ati-relay` hedef adresi |

3. Render'da her alan adının yanındaki **Verify** düğmesine basın. Sertifikalar otomatik verilir
   (birkaç dakika sürebilir).

Bulutlar gri kalmalıdır: istemci adresi ayarı (`ATI_FORWARDED_HOPS=1`) buna göre yapıldı.
Turuncu buluta (Cloudflare vekili) geçmek istenirse önce bu ayarın değişmesi gerekir.

## 5. İndirme deposu: Cloudflare R2 (siz)

1. Cloudflare → **R2 Object Storage** → (ilk kez ise aboneliği etkinleştirin) → **Create bucket**
   → ad: `ati-indir`.
2. Bucket → **Settings → Custom Domains → Connect Domain** → `indir.canarslan.net.tr`
   (DNS kaydını Cloudflare kendisi ekler).
3. Kurulum dosyası hazır olunca (GitHub Actions → Masaüstü → Run workflow ile elle; iş özetinde sürüm,
   boyut ve SHA-256 yazar) dosyayı **sürüm numaralı, değişmeyen bir adla** yükleyin:
   `AI-Trading-Intelligence_0.14.0_x64-setup.exe`. Aynı ada başka dosya yüklemeyin.
4. Yönetim paneli → **Sürümler** → adres
   `https://indir.canarslan.net.tr/AI-Trading-Intelligence_0.14.0_x64-setup.exe`, SHA-256 ve
   boyutla taslak ekleyin, kontrol edin, doğrulama kodunuzla yayınlayın.

## 6. İlk yönetici hesabı (siz)

1. Render → `ati-api` → **Shell**:

   ```bash
   ati-cloud-admin invite --email <e-posta adresiniz> --name "<Adınız Soyadınız>"
   ```

2. Çıkan `https://admin.canarslan.net.tr/yonetim/davet?token=…` bağlantısını 72 saat içinde açın:
   parola belirleyin, doğrulama uygulamasını (Google Authenticator, 1Password vb.) kurun,
   10 kurtarma kodunu güvenli yere kaydedin.
3. **Ayarlar → Şirket bilgileri**, **Paketler ve fiyatlar** buradan yönetilir.

## 7. Kontrol listesi (siz → bana haber verin)

- [ ] `https://canarslan.net.tr` açılıyor, `www.` adresi köke yönleniyor
- [ ] `https://canarslan.net.tr/indir` açılıyor ("yakında" veya yayınladığınız sürüm)
- [ ] `https://admin.canarslan.net.tr/yonetim` giriş sayfası; `canarslan.net.tr/yonetim` 404
- [ ] `https://api.canarslan.net.tr/ready` → `{"status":"ready"}`
- [ ] `https://relay.canarslan.net.tr/health` → `"status":"ok"`
- [ ] **İstemci adresi:** Yönetim → Denetim kaydı'ndaki `admin.login` satırının IP'si,
      <https://www.cloudflare.com/cdn-cgi/trace> sayfasındaki `ip=` değeriyle aynı mı?
      (Farklıysa bana yazın; hız sınırları IP'ye göre çalışır.)

## Henüz bağlı olmayanlar

- **E-posta gönderimi:** E-postalar veritabanında sıraya yazılıyor ama henüz bir e-posta
  sağlayıcısına bağlı değil. Müşteri kaydındaki doğrulama ve parola sıfırlama e-postaları bu
  bağlanana kadar gitmez (yönetici daveti etkilenmez; bağlantı konsolda çıkar).
- **Ödeme:** PayTR veya iyzico test hesabı bilgileri panelden girilir; canlı ödeme G3 onayıyla.
- **Kod imzalama (G6):** O zamana kadar indirme sayfası "imzasız" uyarısı ve SHA-256 doğrulama
  komutu gösterir.
