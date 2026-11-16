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

**Parolanızı veya doğrulama telefonunuzu kaybettiyseniz** (tek yönetici siz olsanız da) sunucuda:

```powershell
powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 yonetici-sifirla -Eposta <yönetici e-postası>
```

Çıkan yeni davet bağlantısıyla yeni parola ve doğrulama uygulaması kurulur; eski parola, eski
oturumlar ve eski kurtarma kodları geçersiz olur. İşlem denetim kaydına yazılır.

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
* **Kampanya ve duyuru şeridi:** panel → **Paketler ve fiyatlar → Genel kampanya** (yüzde indirim,
  bitiş tarihi). Paketler sayfasında hareketli indirim afişi, geri sayım ve kartlarda "%X İNDİRİM"
  etiketi çıkar. **Ayarlar → Duyuru şeridi** sitenin en üstüne ince bir duyuru koyar; duyuru yokken
  şerit yürürlükteki kampanyayı gösterir.
* **Toplu lisans işlemi:** panel → **Lisanslar**: durum süzgeci, satır başındaki kutular ya da "tümünü
  seç" → alttaki çubuktan dondur / dondurmayı kaldır / iptal / sil (iptal ve silme doğrulama kodu ister).
* **Forum:** site → **Forum** (canarslan.net.tr/forum). Müşterinin açtığı konu ve yanıt, panel →
  **Topluluk → Forum onayları**'nda onaylanmadan görünmez; reddederken yazdığınız neden müşteriye
  görünür. Kazanç vaadi, bağlantı ve iletişim bilgisi içeren gönderiler otomatik işaretlenir.
* **Forum üyeleri:** müşterinin ilk gönderisindeki ad kalıcı forum adı olur (başkası aynı adı
  alamaz; "Ekip", "Yönetici" gibi adlar ayrılmıştır). Her üyenin profil sayfası
  (canarslan.net.tr/forum/uye/AD) rütbe sancağını, mesaj ve "Faydalı" sayısını gösterir; liderlik
  tablosu Rütbe sistemi sayfasında. Mesajlarda **Faydalı** (beğeni) ve **Alıntıla** düğmeleri, coin
  konularında **Yükseliş / Düşüş** oylaması vardır (topluluk görüşüdür, yatırım tavsiyesi değildir).
* **Haber çevirisi:** İngilizce kaynakların başlık ve özeti Türkçeye çevrilir (Coin haberleri →
  Türkçe çeviri). Varsayılan ücretsiz MyMemory; isterseniz ücretsiz DeepL API anahtarı girilir.
  Haberin tamamı kopyalanmaz; tamamı kaynak bağlantısındadır.
* **Forum rütbeleri:** canarslan.net.tr/forum/rutbeler. Yayımlanan (onaylı) mesaj sayısıyla
  Seviye 10 Sui'den (başlangıç) Seviye 1 Bitcoin'e (200+ mesaj) yükselinir; ekip ayrı "Ekip" rütbesi
  taşır. Rütbe her mesajın yanında sancak olarak görünür.
* **Coin haberleri:** panel → **Topluluk → Coin haberleri**. Sunucu 15 dakikada bir herkese açık
  kaynaklardan (Binance duyuruları ve yeni işlem çiftleri, Cointelegraph, BTCHaber, Uzmancoin,
  Investing.com Türkiye) başlık ve kısa özet çeker; "Şimdi yenile" ile hemen çekilir. Beğendiğiniz
  haberde **Paylaş** → metni düzenleyip forumda ekip konusu olarak yayımlayın.
  **Otomatik taslak** (varsayılan açık, aynı sayfadan kapatılır): yeni coin haberi (sembolü belli,
  son 48 saatte yayımlanmış listeleme) gelince forum konusu taslağı kendiliğinden hazırlanır ve
  **Forum onayları**'na düşer (menüde bekleyen sayısı görünür). Onaydan önce **Düzenle** ile başlık ve
  metni değiştirebilirsiniz; onaylamadan sitede görünmez. Aynı coin için 24 saatte bir taslak açılır. Aralık `bulut.env`
  içinde `ATI_NEWS_INTERVAL_S` ile değişir (0 kapatır). Forum sayfalarındaki canlı fiyat bandı
  Binance'in herkese açık piyasa verisidir (`ATI_MARKET_DATA_URL=` boş bırakılırsa kapanır).

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

1. GitHub'da depo → **Actions** → soldan **Masaüstü** → sağda **Run workflow** → dal:
   `claude/laughing-hawking-wmt8mo` (en son kod bu daldadır) → yeşil **Run workflow**.
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
koyun (ör. `AI-Trading-Intelligence_0.14.9_x64-setup.exe`). Adresi
`https://indir.canarslan.net.tr/AI-Trading-Intelligence_0.14.9_x64-setup.exe` olur. Sonra yönetim
paneli → **Sürümler**'de bu adres, SHA-256 ve boyutla taslak ekleyip doğrulama kodunuzla
yayınlayın. SHA-256'yı sunucuda şöyle alabilirsiniz:
`(Get-FileHash C:\ATI\indir\<dosya> -Algorithm SHA256).Hash.ToLower()`.

## Sunucu dışı yedek (Cloudflare R2, ücretsiz katman)

Gece yedeği (03:30) sunucuda tutulur; sunucu kaybına karşı şifrelenmiş bir kopyası R2'ye de
yüklenebilir. Şifreleme sunucuda yapılır, Cloudflare içeriği okuyamaz.

1. Cloudflare → **R2** → (ilk kez ise ücretsiz planı etkinleştirin) → **Create bucket**: `ati-yedek`.
2. Bucket → **Settings → Object lifecycle rules**: "30 gün sonra sil" kuralı ekleyin.
3. R2 → **Manage API tokens → Create API token**: izin **Object Read & Write**, yalnızca
   `ati-yedek`. Access Key ID ve Secret Access Key'i not alın (Secret bir kez gösterilir).
4. Sunucuda:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 yedek-bulut-ayarla
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 yedek
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 yedek-bulut-dene
   ```

5. **`bulut.env` dosyasını sunucu dışında saklayın** (şifreli USB, parola yöneticisi). Yedeği açan
   anahtar ve lisans imza anahtarı oradadır; o olmadan yedek açılamaz.

**Geri yükleme** (yeni sunucu): `bulut.env`'i `C:\ATI\ayarlar`'a koyun, R2'den son
`.dump.enc` dosyasını indirin, sonra:

```powershell
cd C:\ATI\uygulama\cloud
# bulut.env değişkenleri yüklüyken (yonet.ps1 ile aynı oturumda):
.\.venv\Scripts\ati-cloud-offsite.exe decrypt ati-YYYYMMDD-HHMM.dump.enc ati.dump
& "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" --no-owner --clean --if-exists -d $env:ATI_DATABASE_URL ati.dump
```

## Ödeme: Lemon Squeezy ve canlı ödeme kilidi

Vergi levhası yoksa kartla (3D Secure) ödeme için **Lemon Squeezy** kullanılabilir: satışı kendi
şirketleri üzerinden yapar, fatura ve KDV onlarda; kazanç size aktarılır. Kazancınızı Türkiye'de
beyan etmeniz gerekebilir; bir mali müşavire danışın.

1. lemonsqueezy.com → mağaza (Store) açın. Para birimi paketlerinizinkiyle aynı olsun.
2. **Products → New product**: ad "AI Trading Intelligence lisansı", tek seferlik ödeme, herhangi bir
   fiyat (her siparişte gerçek tutar site tarafından gönderilir). Kaydedin; ürünün **varyant numarası**
   (Variant ID) ve **mağaza numarası** (Settings → Stores) gerekir.
3. **Settings → API → New API key**: anahtarı kopyalayın (sohbete yapıştırmayın).
4. **Settings → Webhooks → +**: adres yönetim panelinde gösterilir
   (`https://api.canarslan.net.tr/v1/payments/webhooks/lemonsqueezy`); olaylardan `order_created` ve
   `order_refunded`; bir **Signing secret** yazın (en az 8 karakter) ve not alın.
5. Yönetim paneli → **Ayarlar → Ödeme**: Sağlayıcı *Lemon Squeezy*, Mod *Test*, mağaza ve varyant
   numarası, API anahtarı, imza sırrı ve doğrulama kodu → **Kaydet**.
6. Sitede bir paketi satın alın; Lemon Squeezy test kartı: `4242 4242 4242 4242`, ileri bir tarih,
   herhangi bir CVC. Lisans müşteri paneline gelmeli.

**Canlı ödeme kilidi** (gerçek para tahsilatı; yalnızca sizin kararınızla):

```powershell
powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 canli-odeme durum
powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 canli-odeme ac
powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 canli-odeme kapat
```

`ac` onay ifadesi (`CANLI ODEME`) ister ve servisleri yeniden başlatır; ardından panelde Mod *Canlı*,
canlı anahtarlar ve `CANLI ÖDEMEYİ AÇ` gerekir. `bulut.env` dosyasını elle düzenlemeyin.

## Kesinti izleme (ücretsiz)

Sunucu kapanırsa haberiniz olsun: lisans yenilemeleri 72 saatten uzun aksarsa müşterilerin
uygulaması yeni işlem açamaz. **UptimeRobot** (ücretsiz, 5 dakikada bir denetim):

1. uptimerobot.com'da hesap açın → **Add New Monitor** → tür **HTTP(s)**.
2. Üç izleyici ekleyin:
   * `https://canarslan.net.tr` (site)
   * `https://api.canarslan.net.tr/ready` (lisans ve hesap API'si; veritabanı dahil)
   * `https://relay.canarslan.net.tr/health` (telefon aktarma servisi)
3. Uyarı kanalı olarak e-postanızı (ve isterseniz Telegram'ı) seçin.

## Güvenlik notları

* Windows Update açık kalsın. Yönetici parolası güçlü olsun; mümkünse RDP'yi yalnızca kendi IP
  adresinize açın.
* Veritabanı ve iç servisler (8000, 8765, 3000, 5432) yalnızca 127.0.0.1'i dinler; dışarıya kapalı.
* Yedekler sunucuda durur; sunucu kaybına karşı "Sunucu dışı yedek" bölümündeki R2 kopyasını açın.
* Canlı ödeme kapalıdır (`ATI_PAYMENTS_LIVE_ALLOWED=false`); açmak ayrı onay (G3) ister.

## Henüz bağlı olmayanlar

* **E-posta gönderimi:** yukarıdaki Resend adımları yapılana kadar e-postalar kuyrukta bekler
  (yönetici daveti etkilenmez).
* **Kurulum dosyası:** GitHub Actions'ta elle derlenir (yukarıda "İndirme dosyaları"). GitHub'ın
  aylık ücretsiz dakikaları bittiyse kota yenilenince derlenir; o zamana kadar indirme sayfası
  "yakında" gösterir.
