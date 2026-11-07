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
| 2 | Binance veri motoru | ⏭️ Sıradaki |
| 3 | Coin tarama sistemi | |
| 4 | Balina takip sistemi | |
| 5 | Tarihsel veri ve grafik motoru | |
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

### Aşama 2 — Binance veri motoru

**Hedef:** Spot ve USDⓈ-M Futures'ta tüm aktif USDT paritelerini keşfetmek ve gerçek
zamanlı, kesintiye dayanıklı veri akışı sağlamak.

**Çıktılar:**
* `exchange/`: REST istemcisi (httpx), istek imzalama (HMAC-SHA256 ve Ed25519), sunucu
  saati senkronu, ağırlık bütçesi yöneticisi (exchangeInfo `rateLimits` + yanıt
  başlıkları), 429/418 yönetimi.
* `market/discovery.py`: exchangeInfo'dan sembol keşfi, filtre ayrıştırma
  (`SymbolInfo`), `exchange_symbols` tablosuna yazma, yeni listeleme/delist tespiti.
* `market/streams.py`: Parçalı WebSocket bağlantı yöneticisi; abonelik mesaj hız sınırı;
  24 saat dolmadan kesintisiz yenileme; `serverShutdown`; üstel geri çekilme; Futures
  `/public`, `/market` yönlendirmeleri.
* `market/orderbook.py`: Belgelenmiş algoritmayla yerel emir defteri senkronu.
* Normalleştirilmiş olaylar: `TickerUpdate`, `KlineUpdate`, `AggTrade`, `BookDepth`,
  `MarkPrice`, `Liquidation`.
* Hazırlık koşulları: `market_data.spot`, `market_data.futures`.

**Kabul kriterleri:**
* Kaydedilmiş gerçek Binance mesajlarıyla birim testler (çözümleme, emir defteri
  boşluk tespiti, yeniden senkron).
* Sahte WebSocket sunucusuyla: kopma → yeniden bağlanma → motor SAFE_MODE → RUNNING testi.
* Herkese açık veri uç noktalarına karşı canlı duman testi (`data-api.binance.vision`):
  518+ spot USDT paritesinin keşfi, 10 dakikalık akışta veri kaybı/sıra hatası yok.
* Olay döngüsü gecikmesi p99 < 50 ms (tüm semboller, katman 0-1 akışları).

### Aşama 3 — Coin tarama sistemi
Hacim anomalisi (z-skor, saatlik/24 saatlik), ani fiyat hareketi, likidite değişimi, yeni
listeleme, alıcı/satıcı hacmi dengesizliği; tüm semboller paralel. **Kabul:** kayıtlı
veride bilinen olayların tespiti; tüm semboller için ≤ 1 sn yenileme.

### Aşama 4 — Balina takip sistemi
Binance kaynaklı: büyük `aggTrade` işlemleri (sembole göre uyarlanır eşik), emir defteri
duvarları ve çekilmeleri, tasfiye akışı, büyük oyuncu long/short oranları. Zincir üstü:
borsa giriş/çıkışları ve büyük transferler (sağlayıcı seçimi **G4**). Aynı coinde birden
fazla büyük hareket kümelenmesi, geçmiş fiyat etkisi istatistiği. **Kabul:** olayların
`whale_events` tablosuna yazılması; etki istatistiklerinin tarihsel veriyle doğrulanması.

### Aşama 5 — Tarihsel veri ve grafik motoru
`data.binance.vision` toplu arşiv indirme (CHECKSUM), Parquet/DuckDB deposu, artımlı
güncelleme (`history_sync_state`), destek/direnç, trend kırılımı, benzer piyasa koşulu
arama. **Kabul:** listelenme tarihinden bugüne tam geçmiş; ikinci çalıştırmada yalnızca yeni
veri işlenmesi; sorgu performans testleri.

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
