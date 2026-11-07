# 05 — Teknik Geliştirme Planı

Proje 18 aşamada, sırayla geliştirilir. Her aşamanın sonunda: çalışan kod, otomatik
testler (CI'da yeşil), güncellenmiş belge. Bir aşama kabul kriterleri sağlanmadan
"tamamlandı" sayılmaz.

## Onay kapıları (sizin açık onayınız olmadan geçilmez)

| Kod | Konu | Ne zaman |
|---|---|---|
| **G1** | Binance'te **gerçek işlem yetkili** API anahtarı kullanımı | Aşama 10 |
| **G2** | **Gerçek para ile** ilk emir (LIVE modunun etkinleştirilmesi) | Aşama 10-11 sonrası |
| **G3** | Ödeme sağlayıcısı seçimi ve **canlı ödeme** alma | Aşama 17 |
| **G4** | Ücretli veri sağlayıcıları (zincir üstü balina verisi vb.) | Aşama 4 |
| **G5** | Bulut sağlayıcısı, bölge, alan adı ve üretim dağıtımı | Aşama 14-15 |
| **G6** | Kod imzalama sertifikası, Apple Developer hesabı, mağaza başvurusu | Aşama 12-13 |

Kodda karşılığı: `TradingModeController` LIVE geçişinde yapılandırma onayı + çalışma anı
onay ifadesi + tüm kontroller ister; stratejiler `live` aşamasına kayıtlı kullanıcı onayı
olmadan geçemez (SQLite kısıtı); paketler fiyat girilmeden satışa açılamaz (PostgreSQL
kısıtı).

## Aşamalar

| # | Aşama | Durum |
|---|---|---|
| 1 | Sistem mimarisi | ✅ **Tamamlandı** |
| 2 | Binance veri motoru | ✅ **Tamamlandı** |
| 3 | Coin tarama sistemi | ✅ **Tamamlandı** |
| 4 | Balina takip sistemi | ✅ **Tamamlandı** |
| 5 | Tarihsel veri ve grafik motoru | ⏭️ Sıradaki |
| 6 | Yapay zekâ analiz motoru | |
| 7 | Fırsat tespit sistemi | |
| 8 | Backtest | |
| 9 | Paper Trading | |
| 10 | Otomatik işlem motoru | |
| 11 | Risk yönetimi | |
| 12 | Windows EXE | |
| 13 | iOS uygulaması | |
| 14 | Web sitesi | |
| 15 | Lisans sistemi | |
| 16 | Admin paneli | |
| 17 | Ödeme sistemi | |
| 18 | Güvenlik ve performans testleri | |

### Aşama 1 — Sistem mimarisi ✅

**Çıktılar:** Mimari belgeleri (`docs/`), tek depo yapısı, motor çekirdeği (olay veri yolu,
durum makinesi, acil durdurma, işlem modu kilidi, şifreli kasa, API anahtar politikası, log
maskeleme, SQLite + geçişler + hash zincirli denetim kaydı, yerel REST/WS API, tek örnek
kilidi, CLI), bulut PostgreSQL şeması (lisans/cihaz/ödeme/admin/denetim) ve geçiş
çalıştırıcısı, paylaşılan protokol şeması, CI (Windows + Linux).

**Kabul kriterleri (sağlandı):** Motor: 102 test (Windows ve Linux CI; DPAPI testi yalnızca Windows'ta, SIGTERM testi yalnızca POSIX'te çalışır).
Bulut: gerçek PostgreSQL 16'da 53 test. `ruff` ve sıkı mod `mypy` hatasız. Motor alt süreç
olarak başlayıp API üzerinden durdurulabiliyor; SIGTERM ile düzgün kapanıyor. LIVE modu
teknik olarak engelli.

### Aşama 2 — Binance veri motoru ✅

**Hedef:** Spot ve USDⓈ-M Futures'ta tüm aktif USDT paritelerini keşfetmek ve gerçek
zamanlı, kesintiye dayanıklı veri akışı sağlamak.

**Çıktılar (uygulandı):**
* `exchange/`: REST istemcisi, HMAC-SHA256 ve Ed25519 imzalama, sunucu saati senkronu,
  ağırlık bütçesi (exchangeInfo `rateLimits` + `X-MBX-USED-WEIGHT-1M`, öncelik seviyeleri),
  429/418 yönetimi, piyasaya göre uç noktalar ve Futures `/public` / `/market` yönlendirmesi.
* `market/discovery.py`: sembol keşfi, filtre ayrıştırma, evren filtresi (USDT; Futures'ta
  kripto PERPETUAL; stabil coin tabanlıları hariç), yeni listeleme ve kapanma tespiti.
* `market/streams.py`: parçalı bağlantılar, hız sınırlı abonelik, yeniden bağlanma,
  `serverShutdown`, veri gelmeyen bağlantı tespiti, kesintisiz 24 saat yenilemesi.
* `market/orderbook.py`: Spot ve Futures yerel emir defteri algoritmaları.
* `market/gapfill.py`: kopmada kaçırılan işlemlerin REST ile geri alınması, tekrarların elenmesi.
* Hazırlık koşulları `market_data.spot` / `market_data.usdm_futures`; yerel API
  `/v1/market/status`, `/v1/market/tickers`, `/v1/market/focus`.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Gerçek Binance mesajlarıyla birim testler | ✅ 11 mesaj türü, gerçek fikstürlerle |
| Sahte sunucuyla kopma → yeniden bağlanma → SAFE_MODE → RUNNING | ✅ Kopma, sunucu kapanışı, sessiz akış, kesintisiz yenileme senaryoları |
| Tüm spot USDT paritelerinin keşfi | ✅ 518 Spot + 522 Futures sembolü, 2094 akış, 13 bağlantı |
| 10 dakikalık akışta veri kaybı / sıra hatası yok | ✅ 292.482 işlem, **0 eksik**, 0 tekrar, 0 emir defteri yeniden senkronu |
| Olay döngüsü gecikmesi p99 < 50 ms | ✅ En kötü 1 dakikalık pencerede **6,9 ms** |

Not: İlk 10 dakikalık denemede 3 bağlantı kopması oldu ve 45 noktada işlem kaçırıldı. Motor
her kopmada doğru şekilde güvenli moda geçip geri döndü. Bunun üzerine boşluk doldurucu
eklendi. Temiz tekrarlanan denemede kopma olmadığı için boşluk doldurucu canlıda devreye
girmedi; mesaj kaybı senaryoları sahte sunucuyla doğrulandı.

### Aşama 3 — Coin tarama sistemi ✅

**Çıktılar (uygulandı):** `scanner/`. 1040 sembolün her biri için saniyede bir yenilenen
tablo: 1/5/15 dk ve 24 saat değişim, 60 sn hacim ve hacim z-skoru (sembolün son 4 saatlik
dakika dağılımına göre), fiyat z-skoru (dakikalık oynaklığa göre), 60 sn / 5 dk agresif
alış-satış dengesizliği, odak sembollerinde spread, derinlik ve defter dengesizliği. Sinyaller:
hacim patlaması, ani fiyat hareketi, alıcı/satıcı baskısı, derinlik düşüşü, yeni listeleme.
Sinyaller masaüstüne bildirilir ve `market_signals` tablosuna kaydedilir. Yerel API:
`/v1/scanner/top`, `/v1/scanner/signals`.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Kayıtlı veride bilinen olayların tespiti | ✅ Enjekte edilen hacim patlaması, ani hareket, tek yönlü akış ve derinlik çekilmesi tespit edildi; sakin veride sinyal yok. Gerçek Binance mumlarında en büyük hareketli dakika en yüksek z-skorunu aldı |
| Tüm semboller için ≤ 1 sn yenileme | ✅ 1040 sembollük tur testte ~6 ms, gerçek yük altında 12-24 ms |
| Yanlış alarm önlemleri | ✅ Pencere ve temel çizgi dolmadan sinyal yok; sinyal başına bekleme süresi; stabil coin pariteleri evrende yok |

### Aşama 4 — Balina takip sistemi ✅

**Çıktılar (uygulandı):** `whales/`. Yalnızca herkese açık Binance verisi:
- büyük işlemler: aynı milisaniyedeki parçalı dolumlar tek emir sayılır; eşik sembole göre
  öğrenilir (%99,9'luk dilim, alt sınır 50 bin $ Spot / 100 bin $ Futures);
- kümelenme: birikim/dağıtım uyarısı ve Spot-Futures çapraz teyidi;
- emir defteri duvarları: çekilme ve yenilme ayrı ayrı izlenir, kısa ömürlü duvarlar elenir;
- tasfiye zincirleri: Binance saniyede tek tasfiye yayınladığı için toplamlar alt sınırdır;
- büyük oyuncu ve genel long/short oranları, açık pozisyon ve ayrışma uyarısı;
- fiyat etkisi: 1/5/15/60 dk sonraki yönlü getiri, isabet oranı ve standart sapma.

Zincir üstü katman sağlayıcıdan bağımsız bir arayüz ve adres etiketleriyle hazırdır, ancak
**varsayılan olarak kapalıdır** (G4). Kayıtlar `whale_alerts` ve `whale_impacts`
tablolarına yazılır. Yerel API: `/v1/whales/trades|alerts|summary|impact|positioning`.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Olayların veritabanına yazılması | ✅ `whale_alerts`, `whale_impacts`; motor yeniden başlayınca etki istatistikleri geri yüklenir |
| Algılayıcıların doğrulanması | ✅ 20 birim/entegrasyon testi + uçtan uca test (sahte Binance) + gerçek Blockchair yanıt fikstürü |
| Gerçek veriyle çalışma | ✅ 6 dk canlı deneme: ~97 bin emir, 29 balina emri, 11 uyarı (duvar çekilmesi/yenilmesi, birikim, dağıtım), 20 sembolün konumlanma verisi; uyarı/hata logu 0, döngü gecikmesi p99 17,9 ms |
| Etki istatistiklerinin tarihsel veriyle doğrulanması | ⏩ Ölçüm düzeneği canlı veride çalıştı (60 sn ufkunda 27 örnek). Birkaç dakikalık örnek istatistiksel sonuç için yetersizdir; aylarca geriye giden doğrulama Aşama 5'in arşiv motoruyla yapılacak ve Aşama 5'in kabul kriterine eklendi |

Not: Etki istatistiği geçmişte ne olduğunu ölçer; gelecekteki fiyatı **garanti etmez**.
Zincir üstü veri için denenen ücretsiz bir servis, paylaşılan IP nedeniyle 430 hatası verdi;
ücretsiz planlar genellikle ticari kullanıma da izin vermez. Bu yüzden anahtarlı bir sağlayıcı
seçimi ve onayınız (G4) beklenmektedir.

### Aşama 5 — Tarihsel veri ve grafik motoru
`data.binance.vision` toplu arşiv indirme (CHECKSUM), Parquet/DuckDB deposu, artımlı
güncelleme (`history_sync_state`), destek/direnç, trend kırılımı, benzer piyasa koşulu
arama. **Kabul:** listelenme tarihinden bugüne tam geçmiş; ikinci çalıştırmada yalnızca yeni
veri işlenmesi; sorgu performans testleri; balina radarının arşiv işlemleri üzerinde yeniden
oynatılarak fiyat etkisi istatistiklerinin (Aşama 4) uzun dönemli doğrulanması.

### Aşama 6 — Yapay zekâ analiz motoru
Artımlı göstergeler (RSI, MACD, EMA 9/21/50/200, Bollinger, Fibonacci, VWAP, ATR, OBV,
Ichimoku, Stochastic RSI) — referans uygulamalarla sayısal doğrulama. Futures özellikleri
(OI, funding, long/short, tasfiye, emir defteri dengesizliği, taker hacmi). Özellik
deposu, model eğitimi (LightGBM/PyTorch), ONNX dışa aktarma. **Kabul:** göstergelerin
referans değerlerle eşleşmesi; gelecekteki veriye bakma (look-ahead) testleri.

### Aşama 7 — Fırsat tespit sistemi
Teknik, hacim, balina, likidite, trend, emir defteri, tarihsel benzerlik, risk/getiri ve
**işlem maliyetlerinin** (komisyon, spread, kayma, funding) birleşimiyle 0-100 puan.
Puan tek başına emir üretmez; risk kapısı zorunlu. **Kabul:** puanın açıklanabilirliği
(bileşen dökümü), kalibrasyon testleri.

### Aşama 8 — Backtest
Olay güdümlü motor (aynı strateji kodu, `ManualClock`), gerçekçi maliyet ve kayma modeli,
walk-forward ve arındırılmış çapraz doğrulama; metrikler: başarı oranı, Profit Factor,
Sharpe, Sortino, Maksimum Düşüş. **Kabul:** bilinen sonuçlu sentetik senaryolarda doğru
metrikler; look-ahead yok.

### Aşama 9 — Paper Trading ve strateji yarışması
10+ stratejinin aynı canlı veriyi bağımsız değerlendirmesi; sanal yürütücü (emir defteri
tabanlı dolum simülasyonu); performans kayıtları; terfi hattı. **Kabul:** her strateji
için canlı metrik; yeni stratejinin `live` aşamasına otomatik geçmemesi.

### Aşama 10 — Otomatik işlem motoru
Emir yöneticisi (idempotent `clientOrderId`, yeniden deneme, kısmi dolum), kullanıcı veri
akışı (listenKey / Futures `/private`), borsa mutabakatı, spot (kademeli alım/satım, OCO)
ve futures (long/short, borsa tarafı stop-loss/take-profit, trailing stop, kademeli kâr
alma). Önce **Testnet**. API anahtar politikası kontrolü bağlanır. **Kabul:** testnet'te uçtan
uca senaryolar; emir gerçekleşme doğrulaması. **G1/G2 onayı olmadan LIVE açılmaz.**

### Aşama 11 — Risk yönetimi
Bağımsız risk kapısı (işlem başına risk, günlük zarar, maksimum açık pozisyon, kaldıraç,
tasfiye mesafesi) ve ayrı izleyen risk bekçisi; günlük zarar sınırında otomatik durma;
bağlantı kesintisinde güvenli mod. **Kabul:** her kural için ret testleri; risk kapısını
atlayan bir kod yolunun olmadığının testle gösterilmesi.

### Aşama 12 — Windows EXE
Tauri 2 + React; ekranlar: canlı piyasa, tüm coinler, en iyi fırsatlar, balina radarı, AI
analiz, spot/futures, açık pozisyonlar, kâr/zarar, işlem geçmişi, risk, strateji
performansları, bot başlat/durdur. Kurulum paketi (MSI/NSIS), otomatik güncelleme, kod
imzalama (**G6**). **Kabul:** E2E arayüz testleri; temiz Windows makinesinde kurulum testi.

### Aşama 13 — iOS uygulaması
SwiftUI; giriş, lisans aktivasyonu, canlı özet, balina bildirimleri, AI analizleri, sinyaller,
pozisyonlar, kâr/zarar, bot kontrolü, acil durdurma, bildirim merkezi. Aktarma servisi ve
uçtan uca imzalı komutlar. **Kabul:** XCTest + UI testleri; imzasız/tekrar oynatılmış komutun
reddedildiğinin testi.

### Aşama 14 — Web sitesi
Ana sayfa, özellikler, paketler, satın alma, müşteri girişi/paneli, SSS, iletişim, kullanım
koşulları, gizlilik politikası, risk bildirimi. **Kabul:** erişilebilirlik ve performans
denetimi; yasal metinlerin hukukçu onayı.

### Aşama 15 — Lisans sistemi
Anahtar üretimi (CSPRNG + Luhn mod 32), HMAC özet + zarf şifreleme, aktivasyon, Ed25519
lisans kirası, çevrim dışı tolerans, cihaz yönetimi. **Kabul:** kapasite ve çakışma testleri,
hız sınırlama, sahte kira reddi.

### Aşama 16 — Admin paneli
Ayrı giriş + TOTP 2FA + kurtarma kodları; RBAC; lisans üret/toplu üret/iptal/dondur/uzat,
müşteri engelleme, cihaz yönetimi, satış/ödeme raporları, aktif kullanıcı ve lisans
istatistikleri, denetim kaydı görüntüleme. **Kabul:** her uç nokta için yetki testleri.

### Aşama 17 — Ödeme sistemi
Sağlayıcı soyutlaması, webhook imza doğrulama, idempotent teslim (bkz. `04` §1.4), e-posta
teslimi, fatura, iade politikası. **Kabul:** tekrar gönderilen/sahte webhook testleri;
sağlayıcının test ortamında uçtan uca satın alma. **Canlı ödeme G3 onayıyla.**

### Aşama 18 — Güvenlik ve performans testleri
Tehdit modeli gözden geçirme, bağımlılık taraması (SCA), statik analiz, sızma testi,
yük testi (aktarma servisi, lisans uç noktaları), motorun 24+ saatlik dayanıklılık testi,
felaket kurtarma (veritabanı yedeği geri yükleme) tatbikatı.

## Açık kararlar (sizden bilgi gerekecek)

1. **Fiyatlandırma:** 16 paketin fiyatları ve para birimi (şemada boş/pasif).
2. **iOS cihaz politikası:** Şu an varsayılan: cihaz limiti (1/2/3) Windows motorları için,
   iOS eşlikçi cihazlar ayrıca 2 adet. iOS'un da limite sayılmasını isterseniz
   `companion_device_limit` ayarlanır.
3. **Ödeme sağlayıcısı** (bkz. `02` — Paddle/Lemon Squeezy, Stripe, iyzico/PayTR).
4. **Hedef pazarlar ve dil:** Türkçe + İngilizce önerilir.
5. **Şirket ve faturalama:** e-Arşiv/e-Fatura entegratörü.
6. **Bulut sağlayıcısı ve veri bölgesi** (KVKK kapsamında yurt dışına veri aktarımı
   değerlendirilmeli).

## Riskler ve dikkat edilmesi gerekenler

Aşağıdakiler hukuki görüş değildir; ürün çıkmadan önce uzman görüşü alınmalıdır.

* **Mevzuat (Türkiye):** Sermaye Piyasası Kanunu'na 2024'te eklenen kripto varlık hizmet
  sağlayıcılarına ilişkin hükümler ve yatırım danışmanlığı düzenlemeleri, "sinyal" ve
  otomatik işlem yazılımı satışının nasıl konumlandırılacağını etkileyebilir. Ürün,
  kullanıcının kendi hesabında kendi kararıyla çalıştırdığı bir yazılım olarak
  konumlanmalı; yatırım tavsiyesi dili kullanılmamalıdır.
* **Apple App Store:** İnceleme kuralları finansal işlem uygulamaları ve uygulama dışında
  satılan dijital lisanslar konusunda kısıtlar içerir. iOS uygulaması "kullanıcının kendi
  masaüstü yazılımını izleme ve kontrol etme" amaçlı eşlikçi uygulama olarak
  konumlanmalı, uygulama içinde satın alma/fiyat gösterilmemeli; başvuru öncesi güncel
  kurallar kontrol edilmelidir.
* **Binance erişimi:** Binance bazı ülkelerde hizmet vermez (bu geliştirme ortamında da
  `api.binance.com` HTTP 451 döndürdü; herkese açık veri uç noktaları erişilebilir).
  Müşterinin ülkesinde Binance kullanımının yasal ve teknik olarak mümkün olduğu satış
  öncesinde belirtilmelidir.
* **Yazılım koruması:** Kullanıcı bilgisayarında çalışan hiçbir kod kırılmaya karşı tam
  korunamaz. Önlemler: Nuitka derlemesi, imzalı ve süreli lisans kirası, model
  güncellemelerinin lisansla dağıtımı.
* **Model riski:** Geçmiş performans geleceği garanti etmez. Aşırı uyuma karşı walk-forward
  ve paper trading zorunludur; ürün hiçbir yerde kazanç vaat etmez.
