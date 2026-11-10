# canarslan.net.tr'yi kendi Windows sunucunuza (VDS) kurma

Ek ücret yok: site, müşteri paneli, yönetim paneli, lisans/ödeme API'si, iPhone aktarma servisi ve
indirme dosyaları sizin Windows Server VDS'nizde çalışır. Alan adı Cloudflare'de kalır.

**İşlem motoru bu sunucuya kurulmaz;** kendi bilgisayarınızda çalışır. Bu sunucu Binance anahtarı
tutmaz ve tutmamalıdır.

Kurulum betiği ([`kur.ps1`](kur.ps1)) şunları yapar:

* PostgreSQL 16, Node.js 22, uv (Python) ve Caddy'yi resmi adreslerinden indirir; her dosyanın
  özetini (SHA-256/512) ve PostgreSQL'in dijital imzasını doğrulamadan çalıştırmaz.
* Veritabanını yalnızca bu makineden erişilebilir kurar; rastgele parolalar ve lisans/yönetici
  anahtarları üretir (`C:\ATI\ayarlar`, yalnızca yöneticiler okuyabilir).
* Siteyi ve servisleri derler, veritabanı geçişlerini çalıştırır.
* Servisleri zamanlanmış görev olarak kaydeder: sunucu açılınca başlarlar, çökerse yeniden
  başlarlar. Yönetici yetkisi olmayan **YEREL HİZMET** hesabıyla çalışırlar.
* Caddy, `canarslan.net.tr`, `www`, `admin`, `api`, `relay`, `indir` için Let's Encrypt
  sertifikalarını kendisi alır ve yeniler.
* Her gece 03:30'da veritabanı yedeği alır (son 14 yedek, `C:\ATI\yedekler`); ödeme bakımını
  10 dakikada bir çalıştırır.
* Windows güvenlik duvarında yalnızca 80 ve 443 portlarını açar.

## Sizin yapacaklarınız

### 1. Cloudflare DNS (5 dakika)

Cloudflare → `canarslan.net.tr` → **DNS → Records**. Aşağıdaki adlar için varsa eski A, AAAA ve
CNAME kayıtlarını silin, sonra şu **A** kayıtlarını ekleyin. **Proxy status: DNS only** (gri
bulut) olmalı, yoksa sertifika alınamaz:

| Tür | Ad | Değer |
|---|---|---|
| A | `@` | VDS'nizin IP adresi |
| A | `www` | VDS'nizin IP adresi |
| A | `admin` | VDS'nizin IP adresi |
| A | `api` | VDS'nizin IP adresi |
| A | `relay` | VDS'nizin IP adresi |
| A | `indir` | VDS'nizin IP adresi |

### 2. VDS sağlayıcınızın paneli

Sağlayıcınızın panelinde bir güvenlik duvarı varsa **80** ve **443** portlarını gelen bağlantılara
açın. Sunucuda IIS kuruluysa durdurun (aynı portları kullanır; betik bunu denetler).

### 3. Kodu sunucuya alın

1. Uzak masaüstüyle (RDP) VDS'ye bağlanın, tarayıcıda GitHub hesabınıza giriş yapın.
2. Şu adresi açıp ZIP'i indirin:
   `https://github.com/g2w4ypjjrp-lang/Can/archive/refs/heads/claude/laughing-hawking-wmt8mo.zip`
3. ZIP'i `C:\Kurulum` klasörüne çıkarın.

### 4. Kurulumu çalıştırın (15-30 dakika)

Başlat menüsünde **Windows PowerShell**'e sağ tıklayın → **Yönetici olarak çalıştır**:

```powershell
cd C:\Kurulum\Can-claude-laughing-hawking-wmt8mo
Get-ChildItem -Recurse | Unblock-File
powershell -ExecutionPolicy Bypass -File .\deploy\windows-sunucu\kur.ps1 -Eposta <e-posta adresiniz>
```

Sonunda "Kurulum tamamlandı" yazar ve servislerin durumunu gösterir. Kırmızı **HATA** satırı
çıkarsa ekran görüntüsünü bana gönderin.

### 5. Gizli dosyaları yedekleyin (önemli)

`C:\ATI\ayarlar\bulut.env` ve `C:\ATI\ayarlar\postgres-yonetici.txt` dosyalarını sunucu dışında
güvenli bir yere (parola yöneticisi, şifreli USB) kopyalayın. Kimseyle paylaşmayın, bana da
göndermeyin. `bulut.env` kaybolursa yedekteki lisans anahtarları açılamaz.

### 6. İlk yönetici hesabı

Yönetici PowerShell'inde:

```powershell
powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 davet -Eposta <e-posta> -Ad "<Ad Soyad>"
```

Çıkan `https://admin.canarslan.net.tr/yonetim/davet?token=…` bağlantısını 72 saat içinde açın:
parola belirleyin, doğrulama uygulamasını (Google Authenticator vb.) kurun, 10 kurtarma kodunu
saklayın.

### 7. Kontrol edip bana haber verin

- [ ] `https://canarslan.net.tr` açılıyor; `www.` köke yönleniyor
- [ ] `https://canarslan.net.tr/indir` açılıyor
- [ ] `https://admin.canarslan.net.tr/yonetim` giriş sayfası açılıyor
- [ ] `https://api.canarslan.net.tr/ready` → `{"status":"ready"}`
- [ ] Yönetim → **Denetim kaydı**'ndaki `admin.login` satırının IP'si,
      <https://www.cloudflare.com/cdn-cgi/trace> sayfasındaki `ip=` değeriyle aynı

## E-posta gönderimi (Resend, ücretsiz plan)

Kayıt doğrulama, parola sıfırlama ve "lisansınız hazır" e-postaları kuyruğa yazılır; sunucudaki
**Eposta** servisi bunları SMTP ile gönderir. Önerilen sağlayıcı **Resend**: ücretsiz planda ayda
3.000, günde 100 e-posta. Lisans anahtarı e-postayla gönderilmez (panelde parolayla görülür).

1. <https://resend.com> → kayıt olun.
2. **Domains → Add Domain** → `canarslan.net.tr`, **Region: Ireland (eu-west-1)** → ekleyin.
3. **Sign in to Cloudflare** düğmesiyle DNS kayıtlarını (DKIM, SPF) otomatik ekletin; ya da
   gösterilen kayıtları Cloudflare → DNS'e elle ekleyin (**DNS only**). Ad alanına kök alan adını
   yazmayın (`send`, `resend._domainkey`). Doğrulama genelde 15 dakika sürer.
4. Cloudflare → DNS → **Add record**: Type `TXT`, Name `_dmarc`, Content `v=DMARC1; p=none;`
   (bir süre sorunsuz gönderimden sonra `p=quarantine` yapılabilir).
5. Resend → **API Keys → Create API Key** → izin: **Sending access**, alan adı
   `canarslan.net.tr` → anahtarı kopyalayın (bir kez gösterilir; kimseyle paylaşmayın).
6. Sunucuda yönetici PowerShell'inde:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 eposta-ayarla
   ```

   Sorulara Enter ile varsayılanı kabul edin; yalnızca **API anahtarı** sorusunda kopyaladığınız
   anahtarı yapıştırın (ekranda görünmez).
7. Deneyin:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 eposta-dene -Eposta <adresiniz>
   ```

   Komut her adımı `[ OK ]` ya da `[HATA]` ile yazar ve hatanın nedenini söyler:

   | Satır | Neden ve çözüm |
   |---|---|
   | E-posta servisi kurulu değil | Sunucudaki kurulum eski: son ZIP + `kur.ps1` |
   | Ayarlar eksik | `eposta-ayarla` hiç çalıştırılmamış |
   | `…:465 bağlantısı kurulamadı` | VDS sağlayıcınız SMTP portunu engelliyor. Komut açık portu söyler (genelde 2465); `eposta-ayarla` → Port: `2465` |
   | Oturum açılamadı (535) | API anahtarı yanlış/silinmiş: Resend → API Keys → yeni anahtar → `eposta-ayarla` |
   | Gönderen adresi reddedildi / domain not verified | Resend → Domains → `canarslan.net.tr` **Verified** olmalı; DNS kayıtları Resend'in gösterdiğiyle aynı olmalı |

   Ayar düzelip deneme e-postası gidince, bu yüzden takılmış son 3 günün e-postaları kendiliğinden
   yeniden gönderilir. Gönderen alan adı doğrulanmamışken gelen hatalar artık e-postayı kaybettirmez;
   düzelene kadar artan aralıklarla yeniden denenir (en çok 8 kez, ~1 gün).

Not: Resend hesap verilerini ve gönderim kayıtlarını ABD'de tutar (e-postalar İrlanda'dan
gönderilir). Müşteri e-posta adresleri bu nedenle yurt dışına aktarılır; KVKK aydınlatma metninde
belirtilmelidir (hukukçu onayı).

## Paketler, lisanslar ve site görünümü (yönetim paneli)

* **Paketler:** Başlangıçta tüm paketler pasif ve fiyatsızdır (fiyat bir iş kararıdır). Yönetim
  paneli → **Paketler ve fiyatlar**'da fiyat girip paketi etkinleştirince sitede ve satın almada
  görünür. Ödeme sağlayıcısı (PayTR/iyzico) ve canlı ödeme ayrı onay (G3) ister.
* **Elle lisans (kendiniz ya da bir müşteri için):** müşteri önce sitede hesap açar
  (canarslan.net.tr/kayit). Sonra panel → **Lisanslar → Lisans üret**: paket seçin, müşterinin
  e-postasını yazın. Anahtar (`ATI-…`) bir kez gösterilir; müşteri panelinde de görünür. Paket pasif
  olsa da elle lisans üretilebilir (ör. 7 günlük deneme).
* **Uygulamada etkinleştirme:** kurulum paketinde lisans zorunludur; uygulama açılınca anahtar istenir.
  Lisans sunucusunun imza anahtarı `bulut.env` içindedir: bu dosya kaybolursa kurulu uygulamalar
  lisansı doğrulayamaz, yedeği kritik önemdedir.
* **Müşteri silme:** panel → Müşteriler → ayrıntı → **Müşteriyi sil** (yalnızca süper yönetici,
  e-posta yazılarak ve doğrulama koduyla). Kişisel veriler anonimleşir, lisanslar iptal olur;
  siparişler yasal saklama için kalır.
* **Site görünümü:** panel → **Ayarlar → Site görünümü**: Okyanus, Zümrüt, Gün batımı, Altın,
  Grafit. Değişiklik ~30 saniyede sitede görünür.

## Günlük kullanım

| İş | Komut (yönetici PowerShell'i) |
|---|---|
| Durum | `C:\ATI\betikler\yonet.ps1 durum` |
| Yeniden başlat | `C:\ATI\betikler\yonet.ps1 yeniden` |
| Günlükler | `C:\ATI\betikler\yonet.ps1 loglar -Servis api` (`web`, `caddy`, `aktarma`, `eposta`, `odeme`) |
| Elle yedek | `C:\ATI\betikler\yonet.ps1 yedek` |
| Güncelleme | Yeni ZIP'i indirip 3. ve 4. adımları tekrarlayın (ayarlar, anahtarlar ve veritabanı korunur) |

`yonet.ps1` engellenirse başına `powershell -ExecutionPolicy Bypass -File` ekleyin.

## Otomatik güncelleme (bir kez kurulum)

1. Sunucuda bir kez çalıştırın (güncelleme imza anahtarı üretilir, açık anahtar ekrana yazılır):

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 guncelleme-anahtari
   ```

2. Ekranda "AÇIK ANAHTAR" altında yazan satırı Claude'a gönderin (gizli değildir); uygulamaya
   gömülür. Gizli anahtar `C:\ATI\ayarlar\guncelleme.key` dosyasıdır: `bulut.env` gibi yedekleyin.
   Kaybolursa kurulu uygulamalar yeni sürüme kendiliğinden geçemez (elle kurulum gerekir).
3. Açık anahtarın gömüldüğü sürümden itibaren her yeni sürüm, kurulu uygulamalarda "Yeni sürüm
   hazır" şeridiyle görünür; müşteri onaylayınca imza doğrulanıp kurulur.

## İndirme dosyaları

Kurulum dosyasını GitHub derler (ücretsiz kotadan ~25 dakika harcar, bu yüzden elle başlatılır):

1. GitHub'da depo → **Actions** → soldan **Masaüstü** → sağda **Run workflow** → dal: `ana` →
   yeşil **Run workflow**.
2. ~15 dakika sonra çalıştırma yeşil olunca içine girin. Özet bölümünde sürüm, boyut (bayt) ve
   SHA-256 yazar. Sayfanın altındaki **Artifacts** → `ati-windows-installer-unsigned` ZIP'ini
   indirip açın.

Kolay yol (dosyayı indirme klasörüne koyar, imzalar ve forma girilecek değerleri yazar):

```powershell
powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 surum-hazirla -Dosya "<indirdiğiniz ...-setup.exe>"
```

Çıkan değerleri (sürüm, adres, SHA-256, boyut, **güncelleme imzası**) yönetim paneli → Sürümler →
Yeni sürüm formuna girip doğrulama kodunuzla yayınlayın. Elle yapmak isterseniz: Windows kurulum
dosyasını `C:\ATI\indir\` klasörüne **sürüm numaralı, değişmeyen bir adla**
koyun (ör. `AI-Trading-Intelligence_0.12.0_x64-setup.exe`). Adresi
`https://indir.canarslan.net.tr/AI-Trading-Intelligence_0.12.0_x64-setup.exe` olur. Sonra yönetim
paneli → **Sürümler**'de bu adres, SHA-256 ve boyutla taslak ekleyip doğrulama kodunuzla
yayınlayın. SHA-256'yı sunucuda şöyle alabilirsiniz:
`(Get-FileHash C:\ATI\indir\<dosya> -Algorithm SHA256).Hash.ToLower()`.

## Güvenlik notları

* Windows Update açık kalsın. Yönetici parolası güçlü olsun; mümkünse RDP'yi yalnızca kendi IP
  adresinize açın.
* Veritabanı ve iç servisler (8000, 8765, 3000, 5432) yalnızca 127.0.0.1'i dinler; dışarıya kapalı.
* Yedekler aynı sunucuda durur. Sunucu kaybına karşı `C:\ATI\yedekler` klasörünü düzenli olarak
  başka bir yere kopyalayın.
* Canlı ödeme kapalıdır (`ATI_PAYMENTS_LIVE_ALLOWED=false`); açmak ayrı onay (G3) ister.

## Henüz bağlı olmayanlar

* **E-posta gönderimi:** yukarıdaki Resend adımları yapılana kadar e-postalar kuyrukta bekler
  (yönetici daveti etkilenmez).
* **Kurulum dosyası:** GitHub Actions'ta elle derlenir (yukarıda "İndirme dosyaları"). GitHub'ın
  aylık ücretsiz dakikaları bittiyse kota yenilenince derlenir; o zamana kadar indirme sayfası
  "yakında" gösterir.
