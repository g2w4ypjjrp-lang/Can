# En son sürümü yükleme (0.14.7)

0.14.7'de yeni: **telefon kilitliyken bildirim (uygulama indirmeden)**. Telefon sayfasında
"Bildirimleri aç" → işlem açılış/kapanışları, acil durdurma ve önemli uyarılar kilit ekranına gelir.
iPhone'da önce Safari → Paylaş → **Ana Ekrana Ekle** (iOS 16.4+), ana ekrandaki simgeden açıp QR'ı
uygulamanın içindeki **QR kodu okut** düğmesiyle okutun. Bildirimler bilgisayarda şifrelenir; Apple ve
sunucumuz içeriği okuyamaz. İşlem bildirimleri (telefon, kilit ekranı, Telegram) artık **her ayrıntıyı**
yazar: stop ve hedef fiyatı, puan ve gerekçe, kaldıraç; kapanışta giriş→çıkış, net kâr/zarar ve yüzdesi,
kapanış nedeni (stop / hedef / iz süren stop / elle) ve süre.

Bot için **kalite filtreleri** (Bot ayarları → Kalite filtreleri): hedefi stop uzaklığının 1,5 katından
yakın olan işlemlere girilmez (kazanç/risk oranı düşük) ve son 24 saatlik hacmi 25 milyon USDT'nin
altındaki, az işlem gören/yeni listelenmiş coinler elenir. İkisi de değiştirilebilir. Bunlar zararı
azaltmaya yönelik önlemlerdir; kazanç garantisi değildir.

Site güncellemesi (yalnızca sunucu; uygulamayı yeniden derlemek gerekmez): yönetim paneli →
**Paketler ve fiyatlar** → **Genel indirim kampanyası**: bütün ücretli paketlere yüzde indirim (%1–90,
isteğe bağlı ad ve bitiş tarihi). Sitede eski fiyat üstü çizili ve "%X indirim" rozetiyle görünür;
kupon kampanyalı fiyatın üzerine uygulanır, deneme paketi etkilenmez. Yönetim paneli → **Lisanslar** →
lisans ayrıntısı → **Lisansı sil** (neden + doğrulama kodu + onay): anahtar kalıcı olarak geçersiz olur,
listelerden kalkar; denetim kaydı saklanır.

Aynı site güncellemesinde **telefon görünümü yenilendi**: bölüm sekmeleri (Özet, Bot, Pozisyonlar,
Geçmiş, Fırsatlar, Bildirimler), parlayan bakiye kartı ve bu oturumdaki bakiye grafiği, coin rozetleri,
botun sonraki kararı için geri sayım halkası, başarı oranı halkası, yüzen alt düğme çubuğu ve alttan açılan
acil durdurma penceresi. Gerçek para modunda kart kırmızı çerçeveli ve "GERÇEK PARA" etiketli kalır.

0.14.6'da yeni: **yeni logo** (neon degrade rozet, yükselen mumlar, trend çizgisi, hedef düğümü) ve
şekillendirilmiş isim (degrade "AI", kalın "Trading", geniş aralıklı "INTELLIGENCE"); uygulama simgesi,
açılış ekranı, menü, lisans ekranı, site ve telefon sayfasında.

0.14.5'te yeni: **işlem geçmişinde kâr/zarar**: her kapanan işlemin net kâr/zararı (USDT ve %),
giriş/çıkış fiyatı, süre ve bot/elle bilgisi; özet olarak bugün, toplam net, başarı oranı, toplam
kazanç/kayıp, en iyi/en kötü işlem. Ana ekranda son işlemler, İşlemler ve Kâr/zarar sayfalarında
tam liste; telefonda da aynı özet ve son 15 işlem.

0.14.4'te yeni: açık pozisyonlarda **anlık kâr/zarar** (güncel fiyat, USDT ve %, yükselişte yeşil,
düşüşte kırmızı parlama; 2 sn'de bir), ana sayfada toplam açık kâr/zarar; telefonda aynı bilgiler
5 sn'de bir yenilenir.

0.14.3'te yeni: **açılış ekranı** (neon logo ve hazırlık adımları), bir ton daha aydınlık tema,
telefon sayfası neon tasarım ve **Binance bakiyesi**; bilgisayar saati Binance'ten kayınca (-1021)
saat otomatik yeniden eşitlenir; bakiye okunamazsa nedeni ana sayfada yazar; anahtar doğrulaması en
çok 45 sn sürer (geçen süre görünür); beklenmeyen hatalar "Motora ulaşılamadı" yerine gerçek nedeniyle
gösterilir.

0.14.2'de yeni: günlük kilit artık tek bir anlık hatalı okumayla (aktarım, boş yanıt) oluşmaz
(art arda iki okuma gerekir); hatalı kilit, zarar sınırın altındaysa ana sayfadan **Kilidi kaldır**
ile açılır. **Küçük hesap**: risk payıyla çıkan miktar Binance'in en küçük emrinin altındaysa risk
sınırı içinde en küçük emir açılır (Bot ayarlarından kapatılabilir).

0.14.1'de yeni: **neon tema** (bir ton aydınlık lacivert zemin, camgöbeği/eflatun vurgular) ve
ana sayfanın en üstünde **Binance bakiyesi** (toplam USDT, açık pozisyonların kâr/zararı, piyasa
başına cüzdan ve kullanılabilir tutar; 15 sn'de bir yenilenir).

0.14.0'da yeni: **sade arayüz** (Kontrol paneli, İşlemler, Fırsatlar, Piyasa; diğer ekranlar
"Gelişmiş" altında), **acil durdurma her ekranın üst çubuğunda**, ana ekranda hesap / özsermaye /
günlük zarar / açık pozisyon kutuları, gerçek hesap anahtarı varken deneme (Demo) bölümleri katlanır,
**bot açık/kapalı durumu kalıcı** (uygulama yeniden açılınca bot açık gelir; gerçek para güvenlik
gereği her açılışta yeniden onaylanır).

0.13.3'te yeni: **telefonun kamerasıyla QR okutunca tarayıcıda izleme sayfası** (uygulama gerekmez),
**karar aralığı** seçimi (1 dk / 5 dk / 15 dk / 1 saat), motor yeniden açıldığında piyasa akışının
başlamaması hatası düzeltildi (güvenli modda kalıp işlem açmıyordu), modern arayüz.

0.13.2'de yeni: Genel bakışta **Bot paneli** (bot neden işlem açmıyor + Düzelt düğmeleri, sonraki
karar saati, en yüksek puanlı adaylar), coin listesi açılışta birkaç saniyede dolar, fırsat taraması
büyük coinlerden başlar ve ilerlemesi görünür, bot başlatılınca son saatin geçerli sinyalleri hemen
değerlendirilir (sinyal 15 dk geçerli, fiyat kaçtıysa girilmez), yönetim panelinde havuzdaki lisansı
müşteriye atama.

Önceki sürümlerden: Demo para / Gerçek para seçeneği, formasyon tanıma, piyasa rejimi ve üst zaman dilimi,
kendini ayarlayan strateji ağırlıkları, iz süren stop, kayıp serisi molası, müşteri iki adımlı
doğrulaması, indirim kuponları, isteğe bağlı hata raporları, bot ayarları ekranı.

## A. Web sitesi ve sunucu (VDS) — yaklaşık 20 dakika

1. Uzak Masaüstü (RDP) ile VDS'ye bağlanın.
2. Önce yedek alın (yönetici PowerShell):
   `powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 yedek`
3. Tarayıcıda GitHub'a giriş yapıp en son kodu indirin:
   `https://github.com/g2w4ypjjrp-lang/Can/archive/refs/heads/claude/laughing-hawking-wmt8mo.zip`
4. `C:\Kurulum\Can-claude-laughing-hawking-wmt8mo` klasörü varsa silin; ZIP'i `C:\Kurulum`'a çıkarın.
5. Başlat → **Windows PowerShell** → sağ tık → **Yönetici olarak çalıştır**:

   ```powershell
   cd C:\Kurulum\Can-claude-laughing-hawking-wmt8mo
   Get-ChildItem -Recurse | Unblock-File
   powershell -ExecutionPolicy Bypass -File .\deploy\windows-sunucu\kur.ps1 -Eposta <e-posta adresiniz>
   ```

   Ayarlar, gizli anahtarlar ve veritabanı korunur; yeni veritabanı değişiklikleri (kuponlar, iki
   adımlı doğrulama, hata raporları) otomatik uygulanır. Sonunda "Kurulum tamamlandı" yazar.
6. Kontrol: `C:\ATI\betikler\yonet.ps1 durum` → tüm servisler "Running".
   Sitede: Müşteri paneli → **Güvenlik** bölümü; yönetim paneli → **İndirim kuponları** ve
   **Hata raporları** sayfaları görünmeli.

## B. Uygulama (Windows kurulum dosyası)

Kurulum dosyasını GitHub Actions derler. Ücretsiz dakika kotası dolduysa çalıştırma birkaç
saniyede kırmızıya düşer; kota ay başında yenilenir (ya da GitHub → Settings → Billing'de küçük bir
harcama sınırı tanımlanabilir).

1. GitHub → depo → **Actions** → **Masaüstü** → **Run workflow** → dal:
   `claude/laughing-hawking-wmt8mo` → **Run workflow**. Yaklaşık 25 dakika sürer.
2. Yeşil olunca çalıştırmanın altındaki **Artifacts** → `ati-windows-installer-unsigned` ZIP'ini
   indirip açın: `AI Trading Intelligence_0.14.7_x64-setup.exe`.
3. Dosyayı VDS'ye kopyalayıp hazırlayın (indirme klasörüne koyar, SHA-256'yı ve varsa güncelleme
   imzasını yazar):

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 surum-hazirla -Dosya "<setup.exe yolu>"
   ```

4. Yönetim paneli → **Sürümler** → Yeni sürüm: ekrandaki sürüm (0.14.7), adres, SHA-256, boyut ve
   imzayı girin → doğrulama kodunuzla **Yayınla**. Artık canarslan.net.tr/indir sayfasında görünür.

## C. Bilgisayarınızda kurulum / güncelleme

1. canarslan.net.tr/indir → kurulum dosyasını indirin, çift tıklayın. Windows "Bilgisayarınız
   korundu" derse **Ek bilgi → Yine de çalıştır** (kod imzalama sertifikası alınana kadar).
2. Eski sürümün üzerine kurulur; lisans, anahtarlar ve ayarlar korunur.
3. Uygulama açılınca: Ayarlar → **İşlem modu**. Önce **Demo para** ile deneyin.
4. Gerçek para için: binance.com → API Yönetimi → yeni anahtar (Okuma + Vadeli işlemler / Spot;
   **para çekme kapalı**, mümkünse IP kısıtlı) → Ayarlar → **Binance gerçek hesap anahtarları** →
   kaydedin → İşlem modu → **Gerçek para** → onay ifadesini yazın. Uygulama yeniden başlayınca
   güvenlik için sanal moda döner; her seferinde yeniden onaylanır.

Otomatik güncelleme: `yonet.ps1 guncelleme-anahtari` çıktısındaki **açık anahtarı** gönderdiğinizde
uygulamaya gömülür; o sürümden sonra yeni sürümler uygulama içinden tek tıkla kurulur.
