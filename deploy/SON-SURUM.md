# En son sürümü yükleme (0.13.2)

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
   indirip açın: `AI Trading Intelligence_0.13.2_x64-setup.exe`.
3. Dosyayı VDS'ye kopyalayıp hazırlayın (indirme klasörüne koyar, SHA-256'yı ve varsa güncelleme
   imzasını yazar):

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 surum-hazirla -Dosya "<setup.exe yolu>"
   ```

4. Yönetim paneli → **Sürümler** → Yeni sürüm: ekrandaki sürüm (0.13.2), adres, SHA-256, boyut ve
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
