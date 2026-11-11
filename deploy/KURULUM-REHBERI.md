# AI Trading Intelligence — Baştan sona kurulum rehberi

Üç parça var:

| Parça | Nerede çalışır | Ne yapar |
|---|---|---|
| **Web sitesi + bulut servisleri** | Windows VDS (canarslan.net.tr) | Site, müşteri paneli, yönetim paneli, lisans/ödeme API'si, telefon aktarma servisi, indirme dosyaları |
| **Masaüstü uygulaması (bot)** | Sizin (ve müşterilerin) Windows bilgisayarı | İşlem motoru, Binance bağlantısı, bot. **Binance anahtarları yalnızca burada durur.** |
| **iPhone uygulaması** | Telefon | QR ile eşleşip botu izler/durdurur (App Store için Apple geliştirici hesabı gerekir) |

Önce **A** (bir kez), sonra **B** (her yeni sürümde), sonra **C** (her bilgisayarda).

---

## A. Web sitesi ve sunucu (VDS) — ilk kurulum

### A1. Cloudflare DNS (5 dk)
Cloudflare → `canarslan.net.tr` → **DNS → Records**. Aşağıdaki adlar için eski A/AAAA/CNAME
kayıtlarını silip **A** kaydı ekleyin; **Proxy status: DNS only (gri bulut)**:

`@`, `www`, `admin`, `api`, `relay`, `indir` → değer: VDS'nin IP adresi.

### A2. VDS sağlayıcı paneli
Panelde güvenlik duvarı varsa **80** ve **443** portlarını açın. Sunucuda IIS varsa durdurun.

### A3. Kodu sunucuya alın
1. Uzak Masaüstü (RDP) ile VDS'ye bağlanın; tarayıcıda GitHub'a giriş yapın.
2. İndirin: `https://github.com/g2w4ypjjrp-lang/Can/archive/refs/heads/claude/laughing-hawking-wmt8mo.zip`
3. `C:\Kurulum` klasörüne çıkarın (eski `Can-claude-laughing-hawking-wmt8mo` klasörü varsa önce silin).

### A4. Kurulum (15–30 dk)
Başlat → **Windows PowerShell** → sağ tık → **Yönetici olarak çalıştır**:
```powershell
cd C:\Kurulum\Can-claude-laughing-hawking-wmt8mo
Get-ChildItem -Recurse | Unblock-File
powershell -ExecutionPolicy Bypass -File .\deploy\windows-sunucu\kur.ps1 -Eposta <e-posta adresiniz>
```
Sonunda "Kurulum tamamlandı" yazar. Kırmızı **HATA** satırı çıkarsa ekran görüntüsünü gönderin.

### A5. Gizli dosyaları yedekleyin (kritik)
`C:\ATI\ayarlar\bulut.env` ve `C:\ATI\ayarlar\postgres-yonetici.txt` → sunucu dışında güvenli bir
yere (parola yöneticisi / şifreli USB). Kimseyle (bana da) paylaşmayın. `bulut.env` kaybolursa
lisanslar ve yedekler açılamaz.

### A6. İlk yönetici hesabı
```powershell
powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 davet -Eposta <e-posta> -Ad "<Ad Soyad>"
```
Çıkan `https://admin.canarslan.net.tr/yonetim/davet?token=…` bağlantısını 72 saat içinde açın:
parola belirleyin, **doğrulama uygulamasıyla** QR'ı okutun (aşağıda "SMS ve doğrulama kodu"),
10 kurtarma kodunu saklayın.

### A7. Kontrol
- `https://canarslan.net.tr` ve `/indir` açılıyor
- `https://admin.canarslan.net.tr/yonetim` giriş sayfası açılıyor
- `https://api.canarslan.net.tr/ready` → `{"status":"ready"}`
- `C:\ATI\betikler\yonet.ps1 durum` → servisler çalışıyor

### A8. E-posta (Resend, ücretsiz)
1. resend.com → kayıt → **Domains → Add Domain** → `canarslan.net.tr`, bölge **Ireland**.
2. **Sign in to Cloudflare** ile DKIM/SPF kayıtlarını ekletin (ya da elle, **DNS only**).
3. Cloudflare → DNS → TXT `_dmarc` = `v=DMARC1; p=none;`
4. Resend → **API Keys → Create** (Sending access) → anahtarı kopyalayın.
5. Sunucuda: `yonet.ps1 eposta-ayarla` (yalnızca API anahtarı sorusuna yapıştırın), sonra
   `yonet.ps1 eposta-dene -Eposta <adresiniz>`. Her satır `[ OK ]` ya da `[HATA]` + çözümüyle yazılır
   (port engeli varsa genelde 2465 kullanın).

### A9. Yönetim paneli ayarları
- **Paketler ve fiyatlar:** fiyat girip paketi etkinleştirin (başlangıçta hepsi pasif).
- **Ayarlar:** şirket bilgileri (yasal metinlerde görünür), **Site görünümü** (5 tasarım).
- **Lisanslar → Lisans üret:** müşteri sitede hesap açtıktan sonra e-postasıyla elle lisans.
- **İndirim kuponları:** yüzde/tutar, kullanım sınırı, kişiye özel kod.
- **Hata raporları:** uygulamada açanların ayıklanmış hata raporları.
- Ödeme sağlayıcısı (PayTR/iyzico) ve **canlı ödeme ayrı onay ister**; şu an kapalı.

### A10. Güvenlik ve süreklilik (önerilir)
- **Otomatik güncelleme anahtarı:** `yonet.ps1 guncelleme-anahtari` → "AÇIK ANAHTAR" satırını bana
  gönderin (gizli değildir). `C:\ATI\ayarlar\guncelleme.key` dosyasını yedekleyin.
- **Sunucu dışı yedek (Cloudflare R2, ücretsiz):** bucket `ati-yedek` + 30 gün silme kuralı +
  API token → `yonet.ps1 yedek-bulut-ayarla`, `yonet.ps1 yedek`, `yonet.ps1 yedek-bulut-dene`.
- **Kesinti izleme (UptimeRobot, ücretsiz):** `https://canarslan.net.tr`,
  `https://api.canarslan.net.tr/ready`, `https://relay.canarslan.net.tr/health`.
- Windows Update açık; RDP mümkünse yalnızca kendi IP'nize açık.

### Sunucuyu güncelleme (her yeni sürümde)
1. `yonet.ps1 yedek`
2. A3 (yeni ZIP) + A4 (aynı komut). Ayarlar, anahtarlar ve veritabanı korunur; veritabanı
   değişiklikleri otomatik uygulanır.

---

## B. Uygulama kurulum dosyasını hazırlama (her yeni sürümde)

Kurulum dosyasını (EXE) GitHub derler.

1. GitHub → depo → **Actions** → **Masaüstü** → **Run workflow** → dal
   `claude/laughing-hawking-wmt8mo` → **Run workflow** (~25 dk).
   *Ücretsiz dakika kotası dolduysa çalıştırma birkaç saniyede kırmızı olur; kota ay başında
   yenilenir ya da GitHub → Settings → Billing'de küçük bir harcama sınırı tanımlanabilir.*
2. Yeşil olunca **Artifacts** → `ati-windows-installer-unsigned` → ZIP'teki `…_x64-setup.exe`.
3. Dosyayı VDS'ye kopyalayın ve hazırlayın:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 surum-hazirla -Dosya "<setup.exe yolu>"
   ```
4. Yönetim paneli → **Sürümler** → yeni sürüm: ekrandaki sürüm, adres, SHA-256, boyut, imza →
   doğrulama kodunuzla **Yayınla**. canarslan.net.tr/indir sayfasında görünür.

---

## C. Bilgisayara kurulum ve botu çalıştırma

1. canarslan.net.tr/indir → kurulum dosyasını indirip çalıştırın. Windows "Bilgisayarınız korundu"
   derse **Ek bilgi → Yine de çalıştır** (kod imzalama sertifikası alınana kadar). Eski sürümün
   üzerine kurulur; lisans ve ayarlar korunur.
2. Açılışta **lisans anahtarını** (`ATI-XXXX-…`) girin (müşteri paneli → Lisanslarım).
3. **Demo para (önerilen ilk adım):** demo.binance.com → API Management → Create API →
   uygulamada Ayarlar → **Demo Trading anahtarları** → Futures (ve/veya Spot) → Doğrula ve kaydet.
   Ayarlar → İşlem modu → **Demo para**.
4. **Bot:** Spot / Futures işlemler ekranı → **Bot ayarları** (puan eşiği, risk, kaldıraç, iz süren
   stop, kayıp molası) → Genel bakış → **Botu başlat**.
5. **Gerçek para (isteğe bağlı):** binance.com → API Yönetimi → yeni anahtar: **Okuma** +
   **Vadeli işlemler** (Spot için Spot işlem), **para çekme KAPALI**, mümkünse IP kısıtlı →
   uygulamada Ayarlar → **Binance gerçek hesap anahtarları** → kaydedin (para çekme açıksa
   reddedilir) → İşlem modu → **Gerçek para** → onay ifadesini yazın. Uygulama yeniden başlayınca
   sanal moda döner; her seferinde yeniden onaylanır.
6. **Telefon:** Telefon ekranı → "Telefondan kontrol"ü açın → iPhone uygulamasıyla QR'ı okutun.
7. **Telegram (isteğe bağlı):** Ayarlar → Telegram bildirimleri → @BotFather'dan bot anahtarı →
   botunuza /start yazın → Sohbeti bul → Kaydet.
8. Bilgisayar ve uygulama açık kalmalı; kapalıyken yeni işlem açılmaz (borsadaki stoplar kalır).
   Windows saatini otomatik eşitlemeye ayarlayın (Binance -1021 hatasını önler).

---

## SMS ve doğrulama kodu

**Sistemde SMS yoktur ve SMS gerekmez.** Giriş kodları telefona SMS ile gelmez; telefonunuzdaki
bir **doğrulama uygulaması** üretir (TOTP):

- **Nerede kullanılır:** yönetim paneli girişi (zorunlu) ve hassas işlemler (lisans anahtarı
  gösterme, iade, müşteri silme, sürüm yayınlama); müşteri hesabında isteğe bağlı **iki adımlı
  doğrulama** (Panel → Güvenlik).
- **Kurulum:** Google Authenticator, Microsoft Authenticator veya 1Password'ü indirin → davet /
  Güvenlik ekranındaki **QR kodu okutun** → uygulama her 30 saniyede bir yeni **6 haneli kod**
  gösterir → girişte o kodu yazın.
- **Telefon kaybolursa:** kurulumda verilen 10 **kurtarma kodundan** birini kod yerine yazın (her biri
  bir kez çalışır). Kurtarma kodları da yoksa sunucuda `yonet.ps1 davet` ile yeni bir yönetici
  hesabı açılır.
- **Kod "hatalı" diyorsa:** telefonun saati otomatik olmalı (Ayarlar → Tarih ve Saat → Otomatik).
- **E-posta doğrulama** (kayıt, parola sıfırlama) SMS değil **e-postayla** gelir (A8, Resend).

Neden SMS değil: SMS kodu SIM kopyalama ile çalınabilir ve SMS sağlayıcısı (Netgsm, İleti Merkezi
vb.) aylık ücretlidir; doğrulama uygulaması ücretsiz ve daha güvenlidir. SMS istenirse ücretli
sağlayıcı aboneliği ve ayrı onay gerekir.
