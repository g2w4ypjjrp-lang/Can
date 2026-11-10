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

## Günlük kullanım

| İş | Komut (yönetici PowerShell'i) |
|---|---|
| Durum | `C:\ATI\betikler\yonet.ps1 durum` |
| Yeniden başlat | `C:\ATI\betikler\yonet.ps1 yeniden` |
| Günlükler | `C:\ATI\betikler\yonet.ps1 loglar -Servis api` (`web`, `caddy`, `aktarma`, `odeme`) |
| Elle yedek | `C:\ATI\betikler\yonet.ps1 yedek` |
| Güncelleme | Yeni ZIP'i indirip 3. ve 4. adımları tekrarlayın (ayarlar, anahtarlar ve veritabanı korunur) |

`yonet.ps1` engellenirse başına `powershell -ExecutionPolicy Bypass -File` ekleyin.

## İndirme dosyaları

Windows kurulum dosyasını `C:\ATI\indir\` klasörüne **sürüm numaralı, değişmeyen bir adla**
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

* **E-posta gönderimi:** müşteri kaydındaki doğrulama ve parola sıfırlama e-postaları bir e-posta
  sağlayıcısı bağlanana kadar gitmez (yönetici daveti etkilenmez).
* **Kurulum dosyası:** GitHub Actions'ta derlenir; Actions çalışana kadar indirme sayfası
  "yakında" gösterir.
