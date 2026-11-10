# 06 — Güvenlik Tasarımı

## 1. Korunan varlıklar ve tehditler

| Varlık | Tehdit | Önlem | Durum |
|---|---|---|---|
| Binance API anahtarı | Diskten çalınma, loglara sızma, buluta gönderilme | DPAPI ile kullanıcıya bağlı şifreleme; kayıt adına bağlı ek doğrulanmış veri (AAD); log maskeleme; anahtar asla bilgisayardan çıkmaz | ✅ Aşama 1 |
| Kullanıcı fonları | Para çekme yetkili anahtarın kötüye kullanımı | Para çekme / iç transfer / evrensel transfer yetkisi açık anahtar **reddedilir**; IP kısıtı yoksa uyarı | ✅ Politika (Aşama 1), uç nokta çağrısı Aşama 10 |
| Kullanıcı fonları | Hatalı/istem dışı gerçek işlem | Varsayılan PAPER; LIVE için ayar + onay ifadesi + tüm kontroller; Aşama 1'de LIVE imkânsız; kalıcı acil durdurma | ✅ |
| Kullanıcı fonları | Bilgisayar/internet kesintisinde sahipsiz pozisyon | Borsa tarafı koruyucu stop emirleri; güvenli mod; açılışta mutabakat | ✅ Aşama 10-11 |
| Motorun sürekliliği | Olay döngüsünün kilitlenmesi (acil durdurma dahil yanıtsız kalma), bellek/görev sızıntısı | `settle()` döngü hatası Aşama 18'de bulundu ve düzeltildi (gerileme testi); testlerde süre aşımı; CI'da Windows ve Linux'ta dayanıklılık testi (bellek, görev sayısı, döngü gecikmesi, acil durdurma süresi) | ✅ Aşama 18 |
| Yerel kontrol API'si | Aynı makinedeki kötü niyetli web sitesi (DNS rebinding / CSRF), yerel ağdan erişim | Yalnızca loopback; Bearer belirteç (sabit zamanlı karşılaştırma); `Host` başlığı denetimi; WebSocket'te `Origin` denetimi ve ilk mesajda kimlik doğrulama; Windows'ta `SO_EXCLUSIVEADDRUSE`. Aşama 18: tüm rotalar otomatik taranır (belirteçsiz yeni uç nokta testi düşürür) | ✅ |
| Yerel durum | Aynı hesapta iki motorun çift emir göndermesi | İşletim sistemi düzeyinde tek örnek kilidi | ✅ |
| Denetim kaydı | Sessizce değiştirme/silme | Yerel: SQLite tetikleyicileri + SHA-256 hash zinciri (`verify-audit`). Bulut: tetikleyiciler + `audit_log_verify()`; süper kullanıcı tetikleyiciyi kapatsa bile değişiklik tespit edilir | ✅ |
| Müşteri parolaları | Veritabanı sızıntısı | Yalnızca Argon2id (şemada zorunlu); oturum belirteci veritabanında yalnızca SHA-256 özetiyle | ✅ Aşama 14 |
| Müşteri hesapları ve web API'si | CSRF, başka müşterinin verisine erişim (IDOR), enjeksiyon, aşırı büyük/bozuk istek | Ayrıştırmadan önce istek koruması (`guards.py`: köken, 256 KB gövde, UTF-8, JSON derinliği); her rota bir güvenlik sınıfına atanmak zorunda ve sınıf kuralları tüm rotalarda otomatik sınanır; sahiplik her sorguda; parametreli SQL; toplu atama yok sayılır; CORS yalnızca kendi kökenler; `HttpOnly`, `SameSite=Strict` çerez | ✅ Aşama 14 + 18 |
| Lisans anahtarları | Sızıntı, tahmin, ikinci satış | HMAC-SHA256 + pepper ile arama özeti; KMS zarf şifreleme; 75 bit rastgelelik; hız sınırlama; durum makinesi ve tek seferlik tahsis veritabanında zorunlu; cihaza bağlı Ed25519 kira, imzalı motor istekleri, tekrar oynatma koruması | ✅ Aşama 15 |
| Yönetici paneli | Hesap ele geçirme, yetki aşımı | Ayrı alt alan adı, tablo ve oturum (`Path=/admin`); davet + zorunlu TOTP (kod tekrarı reddi) + kurtarma kodları; 5 hatada kilit; RBAC her uç noktada (otomatik yetki matrisi testi); hassas işlemlerde güncel TOTP (tam anahtar, ödeme anahtarları, canlı ödeme, iade); tüm işlemler denetim kaydında | ✅ Aşama 16 |
| Ödemeler | Sahte veya tekrar gönderilen webhook | İmza doğrulanmadan işlenemez (şema kısıtı); olay kimliği tekil; sipariş satırı kilitlenir; sipariş başına tek başarılı ödeme; birim başına tek lisans; tutar uyuşmazlığında teslim yok; iyzico sonucu imzalı sunucu isteğiyle sorgulanır; üretimde test modu ve simülatör kapalı | ✅ Aşama 17 |
| iOS uzaktan komutları | Bulutun veya ağın ele geçirilmesi, tekrar oynatma | Secure Enclave anahtarıyla imza; motorda doğrulama; zaman damgası + kalıcı sayaç; komut izin listesi; hassas komutlarda Face ID; para çekme/pozisyon açma/sınır değiştirme uzaktan imkânsız | ✅ Aşama 13 |
| iOS ↔ motor mesaj içerikleri | Aktarma servisinin veya işletmecisinin içerikleri okuması, yanlış cihaza yönlendirme | Uçtan uca şifreleme: P-256 ECDH (telefon anahtarı Secure Enclave'de) + HKDF-SHA256 + AES-256-GCM; bağlam (yön, motor, cihaz) şifrelemeye bağlı; önce imza sonra şifreleme; Python–Swift ortak test vektörleri | ✅ Aşama 18 |
| Bulut servislerinin kapasitesi | Yük altında hata, soğuk başlangıçta çökme | Yük testi gerçek sunucularla (CI'da duman testi); soğuk başlangıçta bağlantı havuzunun eşzamanlı açılma hatası Aşama 18'de bulundu ve düzeltildi | ✅ Aşama 18 |
| Bulut verisinin kaybı | Donanım/bölge arızası, hatalı işlem, fidye yazılımı | Yedek → boş veritabanına geri yükleme tatbikatı CI'da her gönderimde (satır sayıları, denetim zinciri, tetikleyiciler, sayaçlar, kira yenileme, anahtar çözme). Yedekler gizli bilgi deposundan ayrı tutulur: yedek tek başına lisans anahtarlarını açamaz. Saklama ve bölge seçimi G5 | ✅ tatbikat / ⏸️ G5 |
| Bulut veritabanı bağlantısı | Ortadaki adam saldırısı | Staging/production'da `sslmode=verify-full` zorunlu (ayar doğrulaması) | ✅ |
| Tedarik zinciri | Kötü niyetli veya açıklı bağımlılık, depoya sızan gizli bilgi | Kilit dosyaları (`uv.lock`, `package-lock.json`, `Cargo.lock`), CI'da `--locked`/`npm ci`; her gönderimde ve haftalık `pip-audit`, `npm audit`, `cargo audit`; depo ve tüm git geçmişinde gizli bilgi taraması (`scripts/secret_scan.py`, öz sınamalı); kod imzalama (G6) | ✅ Aşama 18 (imzalama G6) |

## 2. Gizli bilgi yönetimi

| Gizli bilgi | Nerede saklanır |
|---|---|
| Binance API anahtarı/gizli anahtarı | Kullanıcı bilgisayarı, `secrets` tablosu, DPAPI ile şifreli |
| Yerel API belirteci | Masaüstü kabuğu üretir, ortam değişkeniyle iletir (diske yazılmaz). Bağımsız çalıştırmada `runtime/local-api.json` (yalnızca kullanıcı okuyabilir) |
| Lisans kirası (lease) | Kullanıcı bilgisayarı, `secrets` tablosu |
| iOS cihaz anahtarları (imza, korumalı imza, şifreleme) | Secure Enclave (çıkarılamaz) |
| Motorun uzaktan kontrol anahtarları (Ed25519 kimlik, P-256 şifreleme) | Kullanıcı bilgisayarı, `secrets` tablosu, DPAPI ile şifreli |
| Bulut: DB parolası, lisans pepper'ı, ödeme sağlayıcı anahtarları, kira imzalama anahtarı | Yönetilen gizli bilgi deposu (KMS destekli); depoda veya imajda asla bulunmaz |

## 3. Binance API anahtarı kullanım kuralları

1. Kullanıcıya anahtar oluştururken **yalnızca** "Okuma" + gerekli işlem yetkisi
   (Spot ve/veya Futures) açması söylenir. **Para çekme kesinlikle kapalı.**
2. Mümkünse IP kısıtı (yalnızca kullanıcının bilgisayarının dış IP'si).
3. Motor, anahtar kaydedilir kaydedilmez ve her açılışta yetkileri doğrular
   (`evaluate_api_restrictions`); kural ihlalinde anahtar kullanılmaz ve kullanıcıya
   nedeni gösterilir.
4. Bilinmeyen/eksik yetki alanları **güvensiz** kabul edilir.

## 4. Log ve hata mesajı hijyeni

* Anahtar adına göre maskeleme: `api_key`, `secret`, `signature`, `token`, `password`,
  `authorization`, `listenKey`, `cookie`, `session`, `totp` ...
* Değer biçimine göre maskeleme: 48+ karakterlik alfasayısal dizgiler (API anahtarı/imza
  biçimi), URL'deki `signature=` / `listenKey=` / `apiKey=` parametreleri, `Bearer` belirteçleri.
* Denetim kaydı ayrıntıları da yazılmadan önce maskelenir.
* Test: `test_redact_by_key_name`, `test_redact_by_value_shape`, duman testinde log
  dosyasında belirteç bulunmadığının kontrolü.

## 5. Kişisel veriler (KVKK / GDPR)

* Bulutta yalnızca hesap, lisans, cihaz ve ödeme için gereken minimum veri tutulur; işlem
  verisi ve API anahtarları buluta gönderilmez.
* Cihaz parmak izi ham değil, SHA-256 özeti olarak saklanır.
* Hesap silme: `customers.status = 'deleted'` + kişisel alanların anonimleştirilmesi; yasal
  saklama yükümlülüğü olan fatura kayıtları ayrı tutulur.
* Veri bölgesi ve yurt dışı aktarım kararı açık kararlar listesindedir (`05`).

## 6. Aşama 18 gözden geçirmesi (tehdit modeli, testler, kalan riskler)

**Yöntem:** her bileşenin saldırı yüzeyi rota rota çıkarıldı. Her rota bir güvenlik sınıfına
bağlandı (herkese açık okuma, tarayıcı formu, oturum, imzalı makine isteği, yönetici yetkisi). Sınıf
kuralları tüm rotalarda otomatik denenir; yeni uç nokta sınıflandırılmadan eklenemez. Ek olarak
bağımlılık ve gizli bilgi taraması, yük testi, dayanıklılık testi ve felaket kurtarma tatbikatı
yapıldı.

**Bu aşamada bulunan ve düzeltilen gerçek hatalar (9):**

| # | Bulgu | Etki | Düzeltme |
|---|---|---|---|
| 1 | Motor `settle()`: tamamı bitmiş görevlerde `asyncio.gather` olay döngüsüne dönmüyor | Olay döngüsü kilitlenebilirdi (acil durdurma dahil); Windows CI'da takılma | Bitmiş görevler döngüde çıkarılır; gerileme testi |
| 2 | Bozuk UTF-8 istek gövdesi → 500 | Hata günlüğü şişirme, kararsız yanıt | İstek koruması (UTF-8 denetimi) |
| 3 | Derin iç içe JSON (`[[[[…]]]]`) → `RecursionError` → 500 | Ucuz hizmet dışı bırakma girişimi | JSON derinliği ≤ 32 |
| 4 | Köken denetimi gövde doğrulamasından sonra | Yabancı kökene 422 (sızdırmıyordu ama önce reddetmeli) | Köken ayrıştırmadan önce |
| 5 | Genel istek gövdesi sınırı yok | Belleği büyük gövdeyle doldurma | 256 KB sınır (uzunluk başlığı ve akış) |
| 6 | Bağlantı havuzunun ilk eşzamanlı istekte açılması yarışı | Yeniden başlatmadan hemen sonra gelen ilk istekler 500 | Kilitli açılış; havuz boyutu ayarlanabilir |
| 7 | Uzaktan kontrol mesajları şifresizdi | Aktarma işletmecisi özetleri okuyabilirdi | Uçtan uca şifreleme |
| 8 | Lighthouse CI aracının bağımlılıklarında 16 bilinen açık (geliştirme aracı) | Yalnızca CI makinesi | Araç güncellendi; kalan paket sabitlendi |
| 9 | Motor veritabanı açılışı başarısız olunca (bozuk dosya) SQLite bağlantısı açık kalıyordu | Windows'ta dosya kilitli kalır (bozuk yedek silinemez/değiştirilemez) | Hata yolunda bağlantı kapatılır; Windows CI dayanıklılık/yedek işinde bulundu, gerileme testi |

**Kalan riskler ve önlemleri (bilinçli olarak kabul edilen veya onaya bağlı):**

* **Kullanıcı bilgisayarının ele geçirilmesi:** DPAPI, aynı Windows kullanıcısıyla çalışan
  kötü amaçlı yazılımı durduramaz. Önlem: para çekme yetkili anahtar reddedilir, IP kısıtı
  önerilir, gerçek hesap ayrı onay ister (G1/G2).
* **Yazılımın kırılması:** kullanıcının bilgisayarında çalışan kod tam korunamaz. Önlem:
  imzalı ve süreli kira, Nuitka derlemesi, kod imzalama (G6).
* **Hız sınırları süreç içinde tutulur:** birden fazla API sunucusunda Redis'e taşınmalı
  (dağıtım, G5).
* **Simülatör ve test modu:** üretimde kapalıdır (testle doğrulanır). Sağlayıcının test
  ortamında gerçek deneme, test hesabı bilgileriyle yapılacak.
* **Windows'ta açılış beklemesi (açık iş):** motor açılırken olay döngüsü bir kez ~1,4 sn
  bekliyor (Linux'ta 5 ms). Bu sürede acil durdurma da gecikir. Nedeni Windows CI'daki
  `--debug-slow` çıktısıyla belirlenip giderilecek; kararlı durumda sorun yok (p99 ~16 ms).
* **Dış sızma testi:** bu aşamadaki testler kod içinden ve gerçek sunuculara karşı
  otomatiktir. Yayından önce bağımsız bir sızma testi önerilir (canlı ortam, G5).
