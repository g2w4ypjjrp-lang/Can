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
| **G5** | Bulut sağlayıcısı, bölge ve üretim dağıtımı (alan adı belirlendi: `canarslan.net.tr`, bkz. [`deploy/`](../deploy/)) | Aşama 14-15 |
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
| 5 | Tarihsel veri ve grafik motoru | ✅ **Tamamlandı** |
| 6 | Yapay zekâ analiz motoru | ✅ **Tamamlandı** |
| 7 | Fırsat tespit sistemi | ✅ **Tamamlandı** |
| 8 | Backtest | ✅ **Tamamlandı** |
| 9 | Paper Trading | ✅ **Tamamlandı** |
| 10 | Otomatik işlem motoru | ✅ **Tamamlandı** (test ağı; gerçek hesap G1/G2 ile) |
| 11 | Risk yönetimi | ✅ **Tamamlandı** |
| 12 | Windows EXE | ✅ **Tamamlandı** (imzasız; G6 bekliyor) |
| 13 | iOS uygulaması | ✅ **Tamamlandı** (kod + testler; cihaz/App Store G6, bulut G5) |
| 14 | Web sitesi | ✅ **Tamamlandı** (kod + testler; yasal metinler hukukçu onayı, yayın G5) |
| 15 | Lisans sistemi | ⏭️ Sıradaki |
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

### Aşama 5 — Tarihsel veri ve grafik motoru ✅

**Çıktılar (uygulandı):** `history/`.

- **Arşiv:** `data.binance.vision`'dan sayfalı listeleme ve SHA-256 (`.CHECKSUM`) doğrulamalı
  indirme. Biçim farkları ele alınır: Spot mikrosaniye, Futures başlık satırı.
- **Depo:** DuckDB (`market/history.duckdb`); toplu yükleme, tekrar yazmama, aralık sorgusu,
  yeniden örnekleme (1m → 4h/1d), kapsama ve boşluk ölçümü.
- **Artımlı eşitleme (`history_sync_state`):**
  - Aylık ve günlük dosyalar paralel indirilir, sıralı yazılır; yarıda kesilirse kaldığı
    yerden devam eder.
  - Arşivin dışında kalan uçlar REST ile tamamlanır: arşivden önceki **baş** (ilk eşitlemede)
    ve bugünün **kapanmış** mumları.
  - Veri içindeki boşluklar REST ile onarılır.
  - REST, motorun ortak ağırlık bütçesini düşük öncelikle kullanır.
- **Grafik analizi:**
  - ATR ve dönüş noktaları.
  - Destek/direnç: kümelenmiş dönüşler, dokunma sayısı ve göreli güç.
  - Trend çizgisi kırılımı: her mumda yalnızca o ana kadar kesinleşmiş dönüş noktaları
    kullanılır, ileriye bakılmaz (testle doğrulandı).
- **Benzer piyasa koşulu arama:** z-normalize şekil uzaklığı ve oynaklık filtresi; ileri
  getirilerin ortalaması, medyanı ve pozitif oranı.
- **Balina radarının arşiv işlemleri üzerinde yeniden oynatılması:** canlıdakiyle aynı
  bileşenler; rastgele zamanlardaki temel çizgiyle karşılaştırma; kümelenmiş olaylar ayıklanır.
- **Komutlar:** `ati-engine history-sync`, `ati-engine history-replay`.
- **Yerel API:** `/v1/history/status|sync|candles|levels|trend|similar`.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Listelenme tarihinden bugüne tam geçmiş | ✅ ETHUSDT vadeli: 2019-11-27 (listelenme) → bugünün son kapanmış mumu, **0 eksik**. Arşiv 2019-12-31'de başladığı için baş REST'ten alındı; arşivde eksik olan 2026-10-28 REST'ten onarıldı. BTCUSDT spot: 2017-08-17 → bugün; kalan 126 saat Binance'in kendi kesintileri (REST'te de yok) |
| İkinci çalıştırmada yalnızca yeni veri | ✅ 0 dosya indirildi; yalnızca bugünün yeni kapanan mumları REST'ten (BTC: 14 mum) |
| Sorgu performansı | ✅ 80.725 saatlik mum 0,15 sn'de okunur; destek/direnç 0,003 sn; 9 yıllık trend kırılım taraması 0,2 sn; 62.689 pencerede benzerlik araması 0,17 sn. Testte 525.600 satırlık bir yıl: aylık sorgu ve günlük yeniden örnekleme |
| Balina etkisinin uzun dönemli doğrulanması (Aşama 4'ten) | ✅ 30 günlük yeniden oynatma: Spot BTCUSDT (25,9 milyon işlem, 2.923 bağımsız olay) ve Futures BTCUSDT (32,2 milyon işlem, 2.575 bağımsız olay). Ayrıntı aşağıda |

**Balina etkisi sonucu:**
- Büyük agresif emirlerden sonra fiyat ilk 1 dakikada emir yönünde biraz daha hareket ediyor.
  Spot'ta alış için t=4,5; Futures'ta t=4,3-5,9. Etki 15 dakikadan sonra kayboluyor.
- **Ancak büyüklük çok küçük:** ortalama %0,005-0,01 (0,5-1 baz puan). İşlem ücretinin
  (Spot ~%0,1, Futures ~%0,05) çok altında.
- Sonuç: balina emri **tek başına kârlı bir işlem sinyali değildir**; yalnızca diğer
  sinyallerle birlikte kullanılabilecek yardımcı bir özelliktir. Bu, Aşama 6-7'de puanlamaya
  bu şekilde girecek.
- Kümelenmiş olaylar ayıklanmadan yapılan ilk ölçüm t=7,9 gibi şişkin değerler veriyordu.
  Bu yüzden olaylar arasında en az 15 dakika şartı kondu.

**Bulunan veri sorunları:**
- Binance arşivinde 2026-10-28 günü eksik: vadeli günlük `aggTrades` ve `klines` dosyaları
  yok, Ekim aylık dosyasında 6 mum eksik. Bu boşluk REST ile onarılıyor; yeniden oynatma o
  günü atlıyor ve boşluğu aşan ölçümleri istatistiğe katmıyor.
- Benzer koşul aramasında tek bir aykırı dönem ortalamayı bozabiliyor (BTC 2019-10-25:
  +%15,7). Bu yüzden medyan da raporlanıyor ve her yanıtta "geçmiş sonuç, garanti değildir"
  uyarısı var.

### Aşama 6 — Yapay zekâ analiz motoru ✅

**Çıktılar (uygulandı):**

- **`analysis/indicators.py`:** artımlı göstergeler; her mumda O(1), ısınmada `None`.
  - RSI, MACD, EMA 9/21/50/200, SMA, Bollinger, ATR, OBV
  - Stochastic RSI (ham, %K, %D), Ichimoku (bulut 26 mum önceden hesaplanır), oturum VWAP,
    Fibonacci geri çekilme
- **`analysis/features.py`:** 28 durağan özellik ve 7 Futures özelliği. Aynı kod eğitimde ve
  canlıda çalışır, böylece eğitim/canlı farkı olmaz.
  - Durağan özellikler: uzaklıklar ATR'ye, getiriler log orana, hacim kendi geçmişine göre
    ölçeklenir.
  - Futures özellikleri: funding, açık pozisyon değişimi, büyük oyuncu ve genel long/short,
    agresif alış/satış oranı.
- **`history/futures_data.py`:** Binance arşivinden 5 dakikalık metrikler ve funding.
  - Mumlarla ASOF birleştirme: kapanış anında bilinen son kayıt kullanılır.
  - Bayat veri sınırı: metrik 15 dk, funding 9 saat.
  - Daha geriden başlayan isteklerde eksik baş dönem tamamlanır.
- **`ml/`:**
  - Veri kümesi: ileri getiri etiketi; veri boşluğunda etiket üretilmez.
  - LightGBM ile yürüyen pencere eğitimi: ambargo, eğitim dönemi içinden erken durdurma.
  - Örneklem dışı rapor: AUC, log kaybı ve bilgisiz temel karşılaştırması, Brier,
    kalibrasyon, en iyi %10'luk dilimin maliyet sonrası getirisi, özellik önemleri.
  - ONNX dışa aktarma: LightGBM ile eşleşme doğrulanmadan model kaydedilmez.
  - SHA-256 korumalı model kayıt defteri.
- **Komut ve API:**
  - `ati-engine model-train`
  - `/v1/analysis/snapshot|train|jobs|models|predict`

PyTorch eklenmedi: LightGBM tablo verisinde yeterli ve hafif. Derin model ihtiyacı Aşama 16'da
(öğrenme sistemi) değerlendirilecek.

Tasfiye ve emir defteri dengesizliği **canlıda** mevcut (Aşama 3-4) ama Binance arşivinde
geçmişi yok; bu yüzden modele değil, Aşama 7'deki puanlamaya canlı veriden girecek.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Göstergelerin referans değerlerle eşleşmesi | ✅ TA-Lib ile gerçek BTC verisi ve rastgele yürüyüş üzerinde (göreli fark < 1e-9). EMA (4 periyot), SMA, RSI, ATR, OBV, Bollinger ve Stochastic RSI birebir; MACD tohum farkı söndükten sonra (400. mumdan itibaren). Ichimoku ve VWAP tanımdan yazılmış vektörel referansla |
| İleriye bakma testleri | ✅ Gelecekteki mumlar değiştirildiğinde geçmiş gösterge ve özellik değerleri birebir aynı kalıyor. Futures metrikleri gelecekteki kaydı kullanmıyor (ASOF testi). Yürüyen pencerede eğitim ile test arasında ambargo var |
| Sızıntı kontrolü | ✅ Saf gürültüde örneklem dışı AUC 0,45-0,56 aralığında kalıyor; öğrenilebilir yapay sinyalde AUC > 0,7 |
| ONNX dışa aktarma | ✅ ONNX ve LightGBM tahminleri arasındaki en büyük fark 1,7e-7; değiştirilmiş model dosyası yüklenmiyor |

**Gerçek veriyle model sonuçları** (yürüyen pencere, 5 kat, tamamı örneklem dışı):

| Model | Veri | AUC | En iyi %10, maliyet sonrası |
|---|---|---|---|
| Spot long, 1s, 4 saat ufuk | BTC+ETH 2017-2026, 96.732 test satırı | 0,579 | **-%0,078** |
| Spot short | aynı | 0,566 | **-%0,144** |
| Futures long + Futures özellikleri | BTC+ETH 2022-2026, 50.766 test satırı | 0,547 | **-%0,087** |

Yorum:
- Modeller rastgeleden istatistiksel olarak daha iyi ve iyi kalibre. Her kat 0,54-0,60
  arasında; tahmin %44 → gerçekleşen %43.
- En önemli özellik oynaklık (`atr_pct`). Model çoğunlukla "büyük hareket olacak mı"yı
  öğreniyor, yönü değil.
- **En güvenli tahminlerde bile işlem maliyeti sonrası getiri negatif.** Bu modeller tek başına
  kârlı bir işlem sinyali değildir.
- Futures özelliklerinden büyük oyuncu long/short oranı 5. sırada; sonucu değiştirmiyor.
- Modeller Aşama 7'deki puanın bileşenlerinden biri olacak. Gerçek değerlendirmeyi Aşama 8'deki
  maliyetli backtest yapacak.

### Aşama 7 — Fırsat tespit sistemi ✅

**Çıktılar (uygulandı):**

- **`strategies/`: 14 bağımsız strateji.** Her biri yön, 0-1 güç, yazılı gerekçe ve önerilen
  zarar durdur/hedef (ATR katı) üretir. Bir stratejinin hatası diğerlerini durdurmaz.
  - Trend: EMA trend takibi, Ichimoku bulut trendi.
  - Momentum: MACD kesişimi, Stochastic RSI kesişimi.
  - Ortalamaya dönüş: RSI aşırı bölgeden dönüş, Bollinger bandına dönüş, destek/direnç tepkisi.
  - Kırılım: Bollinger sıkışma kırılımı, Donchian kanal kırılımı.
  - Akış: VWAP geri alımı, hacimli itki.
  - Vadeli: aşırı funding karşıtı, açık pozisyon teyitli trend.
  - Makine öğrenmesi modeli.
- **`scoring/costs.py`:** gidiş-dönüş maliyet.
  - Komisyon (taker, iki yön).
  - Spread ve kayma: odak sembollerinde gerçek emir defterinden, diğerlerinde 24 saatlik
    hacme göre "tahmini" etiketiyle.
  - Vadelide funding: yön ve elde tutma süresine göre.
- **`scoring/score.py`:** 0-100 puan.
  - 8 yönlü bileşen: strateji uzlaşısı, trend, momentum, hacim/agresif akış, balina, emir
    defteri, tarihsel benzerlik, model. Verisi olmayan bileşenin ağırlığı diğerlerine dağıtılır.
  - Cezalar: maliyet/hedef oranı, ödül/risk, likidite, sınırlı veri.
  - Hedef, en yakın karşı seviyeyle sınırlanır.
  - **Dökümdeki puanların toplamı puanı birebir verir.**
- **`scoring/calibration.py`** ve `ati-engine score-calibrate`: puanlama geçmiş veride mum mum
  çalıştırılır ve her puan aralığının maliyet sonrası getirisi ölçülür. Canlı her puanın
  yanında, aynı aralığın geçmişteki isabet oranı ve net getirisi gösterilir.
- **`scoring/live.py`:**
  - 1 dakikalık mumlar puanlama aralığına (varsayılan 1 saat) birleştirilir.
  - REST ile ısınma; son kapanmış mum hemen puanlanır.
  - Eşik üstü (varsayılan 60) puanlar arayüze olay olarak gider ve `opportunities` tablosuna
    yazılır.
  - Eşik üstü adaylara depodaki geçmişten benzerlik eklenir.
- **Yerel API:** `/v1/opportunities`, `/detail` (canlı yoksa depodan değerlendirme),
  `/strategies`, `/calibration`, `/stats`.

**Puan tek başına emir üretmez**; risk kapısı Aşama 11'de zorunlu olacak.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Puanın açıklanabilirliği (bileşen dökümü) | ✅ Her bileşenin ham değeri, ağırlığı, puana katkısı ve gerekçe metni; cezalar ayrı. Testte döküm toplamı = ham puan, ham puan - cezalar = puan. Gerçek örnek, BTCUSDT: trend +17,2, strateji uzlaşısı -10,4 (çelişen), emir defteri +7,1; maliyet cezası -15,4 ("maliyet hedef hareketin %148'i") → puan 0 |
| Kalibrasyon testleri | ✅ Düzenek testi: puana bağlı getiride artan tablo (Spearman > 0,2), gürültüde düz (\|ρ\| < 0,05). Gerçek veri sonuçları aşağıda |
| Canlı çalışma | ✅ Gerçek Binance verisinde 1.026 sembol ısındı ve puanlandı. Isınma sırasında döngü gecikmesi p99 30 ms, sonrasında 20 ms; uyarı/hata logu 0 |

**Gerçek veride kalibrasyon** (BTC+ETH, 1 saat, 4 saat ufuk, canlıya özgü balina/emir
defteri bileşenleri hariç):

| Puan aralığı | Spot n | Spot brüt | Spot net | Futures n | Futures brüt | Futures net |
|---|---|---|---|---|---|---|
| 0-20 | 98.499 | +%0,028 | -%0,232 | 66.146 | +%0,013 | -%0,111 |
| 20-40 | 23.532 | -%0,001 | -%0,248 | 27.051 | +%0,011 | -%0,113 |
| 40-60 | 15.347 | +%0,010 | -%0,238 | 11.564 | -%0,004 | -%0,134 |
| 60-80 | 10.191 | **+%0,127** | -%0,118 | 9.073 | **+%0,097** | -%0,029 |
| 80-100 | 26 | — | — | 11 | — | — |

Yorum:
- 60-80 aralığı brüt getiride belirgin şekilde en iyisi ve isabeti en yüksek (Spot %42, Futures
  %43).
- Ancak maliyet sonrası hiçbir aralık pozitif değil; Futures 60-80 başabaşa yakın.
- 80-100 aralığında örnek çok az (26 ve 11); istatistiksel anlamı yok.
- Bu sonuçlar puanın yanında kullanıcıya gösterilir. Puan bir fırsat göstergesidir, kâr
  vaadi değildir. Gerçek değerlendirme Aşama 8'deki backtest'te (zarar durdur/hedef ile) yapılır.

**Bulunan ve düzeltilen sorun:** Isınma ilk sürümde ayrı bir iş parçacığındaydı. Canlı
ölçümde, Python'un küresel kilidi (GIL) nedeniyle döngü gecikmesi p99 157 ms'ye çıktı. Hesap,
olay döngüsünde küçük parçalara bölündü (her 25 mumda bir döngüye söz verilir); p99 30 ms'ye
indi.

### Aşama 8 — Backtest ✅

**Çıktılar (uygulandı):** `backtest/`.

- **Olay güdümlü motor:**
  - Canlıdaki strateji defteri ve stratejilerle aynı kod.
  - Sinyal mum kapanışında üretilir, emir sonraki açılışta dolar.
  - Zarar durdur/hedef mum içi en yüksek/en düşükle denetlenir. Aynı mumda ikisi de görülürse
    önce zarar durdur varsayılır. Boşlukta açılış fiyatından dolum.
- **Maliyetler:** iki yön komisyon, likiditeye göre spread + kayma, vadelide funding (00/08/16
  UTC).
- **Pozisyon ve risk:** risk tabanlı pozisyon büyüklüğü, kaldıraç ve eşzamanlı pozisyon
  sınırı; Spot yalnızca long.
- **Vadelide tasfiye:** mum içi en kötü fiyatta bakım teminatı altı → tüm pozisyonlar kapanır.
  Hesap eksiye düşmez; açık "sigorta fonu" olarak raporlanır.
- **Metrikler:** başarı oranı, Profit Factor, beklenti, ortalama R, toplam getiri, CAGR,
  Sharpe, Sortino, maksimum düşüş (% ve süre), piyasada kalma, ücret ve funding toplamı.
- **Doğrulama:**
  - Yürüyen pencere: parametre geçmişte seçilir, gelecekte sınanır; test dönemleri tek
    sermaye eğrisinde birleşir.
  - Arındırılmış k-katlı çapraz doğrulama: ambargo ve aşırı uyum olasılığı (PBO).
- **Strateji kayıt defteri:** sonuçlar `strategy_metrics` tablosuna yazılır. Örneklem dışı
  ≥30 işlem, PF ≥ 1,1, Sharpe ≥ 0,5, düşüş ≤ %30 olan strateji `walk_forward` aşamasına
  terfi eder. `live` aşamasına otomatik geçiş kodda ve veritabanı kısıtında engellidir.
- **Komut ve API:**
  - `ati-engine backtest`
  - `/v1/backtest/run|jobs|reports`, `/v1/strategies`

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Bilinen sonuçlu sentetik senaryolarda doğru metrikler | ✅ Elle hesaplanmış senaryolar: hedef (+2R), aynı mumda stop+hedef (stop), boşluk (-3R), komisyon+kayma tam değer, short + funding, Spot'ta short yok sayılması, süre ve ters sinyal çıkışı, portföy/kaldıraç sınırı, tasfiye ve sigorta fonu açığı. Sharpe/Sortino/düşüş/CAGR/PF elle hesaplanan değerlerle eşleşiyor |
| İleriye bakma yok | ✅ Gelecek mumlar değiştirildiğinde kesimden önce kapanan işlemler birebir aynı; her giriş sinyal mumundan sonraki açılışta |
| Walk-forward ve arındırılmış CV | ✅ Parametre yalnızca geçmişten seçiliyor, test dönemleri çakışmıyor; test ile örtüşen işlemler (± ambargo) seçimden çıkarılıyor |

**Gerçek veri sonuçları** (BTC+ETH, 1 saat, 2021-2026, %1 risk/işlem, 24 mum en uzun tutma):

| | Spot (yalnız long, %0,10 ücret) | Futures (long+short, %0,05 ücret, funding) |
|---|---|---|
| Al ve tut | +%181, düşüş -%77 | **-%99,9 (tasfiye: 2021 funding'i + 2022 çöküşü)** |
| Tek stratejiler (tam dönem) | 12 stratejiden 11'i zararda; çoğu -%60…-%99 (ücretler: ör. EMA trend 2.931 işlem, 13.601 $ ücret) | Hacimli itki +%16 (PF 1,69); diğerlerinin çoğu zararda |
| **Hacimli itki, yürüyen pencere (örneklem dışı)** | 85 işlem, PF 0,84, -%7,6 | **47 işlem, PF 1,62, +%12,5, Sharpe 0,68, düşüş %4,9 → terfi** |
| Puan eşiği, tam dönem (seçim yanlılığı var) | ≥70: +%12,4 | ≥70: +%36,4 |
| **Puan eşiği, yürüyen pencere (eşik geçmişte seçildi)** | **-%18,5**, PF 0,86 | +%10,3, PF 1,03, Sharpe 0,21 (terfi yok) |
| Puan eşiği, arındırılmış CV | ortalama R -0,03, **PBO 0,6** | ortalama R +0,01, PBO 0,4 |

Yorum:
- Saatlik mumlarda sık işlem yapan klasik stratejiler, maliyetler nedeniyle sistematik
  olarak zarar ediyor. Bu yüzden canlı işlemde **seçicilik ve maliyet kontrolü zorunlu**.
- Spot'ta "puan ≥70 kârlı" görünümü, tam dönem sonucundan eşik seçmenin yarattığı **seçim
  yanlılığıydı**. Örneklem dışında zarara döndü; PBO 0,6 aşırı uyumu gösteriyor.
- Futures'ta hacimli itki örneklem dışında da kârlı ama **örnek küçük (47 işlem)**. Terfi yalnızca
  bir sonraki sınamaya (Aşama 9, sanal işlem) geçiş demektir. Gerçek para kullanımı değildir;
  canlı aşama kullanıcı onayı (G1/G2) gerektirir.
- Uzun süreli vadeli long (al ve tut), funding ve sert düşüşte tasfiye riskiyle **yok
  olabiliyor**. Model bu riski artık gösteriyor.

### Aşama 9 — Paper Trading ve strateji yarışması ✅

**Çıktılar (uygulandı):**

- **`execution/fills.py`: emir defteri tabanlı sanal dolum.**
  - Odak sembollerinde yerel emir defteri seviye seviye tüketilir; dolum fiyatı hacim ağırlıklı
    ortalamadır ve derinlik yetmezse ceza ile işaretlenir.
  - Diğer sembollerde likiditeye göre tahmini spread + kayma kullanılır.
  - Gerçek borsaya hiçbir istek gitmez.
- **`paper/competition.py`: yarışma.** 13 strateji + fırsat puanı, her piyasa için ayrı sanal
  hesapla (toplam 28 hesap), canlı fırsat motorunun aynı strateji defterinden beslenir.
  - Giriş: en güçlü sinyaller boş yuvalara açılır. Likidite filtresi ve maliyet filtresi
    uygulanır (zarar durdur uzaklığı maliyetten büyük, hedef maliyetin en az 2 katı).
  - Çıkış: zarar durdur/hedef tick düzeyinde; ayrıca süre ve ters sinyal.
  - Vadelide canlı funding uygulanır.
  - Kalıcılık: hesap, pozisyon, işlem ve saatlik sermaye ayrı tablolarda (`0005_paper_competition`).
    Gerçek emir tablolarıyla karışmaz.
- **Eksik mum onarımı** (`scoring/live.py`): motor mumun ortasında başlarsa veya bağlantı
  koparsa, eksik toplanan mum stratejilere verilmez; kapanmış aslı REST'ten alınır.
- **Terfi hattı:**
  - `walk_forward` aşamasındaki strateji yarışmaya girince `paper` olur.
  - 30 gün, 30 işlem, PF ≥ 1,1, Sharpe ≥ 0,5 ve düşüş ≤ %20 sağlanırsa `live_candidate` olur.
  - `live` aşamasına otomatik geçiş kodda ve veritabanı kısıtında engellidir.
- **Yerel API:** `/v1/paper/leaderboard|positions|trades|stats`; arayüze `PaperTradeEvent`.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Her strateji için canlı metrik | ✅ Hesap başına sermaye, işlem, başarı oranı, PF, Sharpe, düşüş, ücret, funding (saatlik sermaye eğrisinden). Strateji başına birleşik metrik `strategy_metrics` (`paper`) tablosunda |
| Yeni stratejinin `live` aşamasına otomatik geçmemesi | ✅ Test: ölçütleri karşılayan strateji yalnızca `live_candidate` oluyor. Kod `live` istemini reddediyor; veritabanı onaysız `live` kaydını CHECK kısıtıyla reddediyor |
| Dolum simülasyonu | ✅ Defter yürütme elle hesaplanan ağırlıklı fiyatla eşleşiyor; derinlik tükenmesi cezalandırılıyor; defter yokken likiditeye göre maliyet artıyor |
| Canlı çalışma (gerçek Binance verisi, 15 dk mumla iki deneme) | ✅ 1.026 sembol, 28 sanal hesap. Mum kapanışında tüm semboller işlendi, 20-31 pozisyon açıldı, binlerce işlem tick düzeyinde denetlendi. Döngü gecikmesi p99 ~23 ms; uyarı/hata logu 0 |

**Canlı denemede bulunan ve düzeltilen iki gerçek sorun:**

1. **Eksik ilk mum.** Motor 19:16'da başladığında 19:15-19:30 mumunun ilk dakikaları
   kaçırılmıştı. 1.026 sembolün tamamında açılış ve hacim yanlıştı ve stratejiler bu yanlış
   mumla işlem açtı. Düzeltme: eksik mum kullanılmıyor, kapanınca REST'ten aslı alınıyor. İkinci
   denemede 20:00 mumunda 1.026 eksik mumun 1.026'sı onarıldı, 0 hata.
2. **Oynaklığı çok düşük coin (UUSDT).** Zarar durdur uzaklığı fiyatın ~%0,01'iydi; %0,2'lik
   gidiş-dönüş komisyonu bunun 20 katı olduğu için işlem -40R ile kapandı. Düzeltme: maliyet
   farkındalıklı giriş filtresi (genel kural, isim listesi değil). İkinci denemede 7 işlem bu
   filtreyle engellendi.

**Not:** Yarışmanın asıl çıktısı zamanla birikecek canlı performanstır. Terfi ölçütü en az 30
gün ister. Bu süre motor kullanıcının bilgisayarında çalıştıkça dolar.

### Aşama 10 — Otomatik işlem motoru ✅ (test ağı; gerçek hesap kilitli)

**Çıktılar (uygulandı):**

- **`execution/orders.py`: emir yöneticisi.**
  - İstemci emir kimliği karardan türetilir (`make_client_id`; Binance deseni, ≤36 karakter).
    Aynı karar ikinci kez gönderilmez.
  - Gönderim sonucu belirsizse (zaman aşımı, 5xx, -1007) emir **yeniden gönderilmez**: önce
    aynı kimlikle borsada sorgulanır; bulunamazsa aynı kimlikle yeniden denenir. Denemeler
    biterse emir "durum bilinmiyor" olarak mutabakata bırakılır.
  - Kısmi dolumlar, dolum tekilleştirme (`trade_id`), REST ile kaçırılan dolum alma ve tetiklenen
    koşullu emirden doğan gerçek emrin dolumlarının bağlanması.
- **`execution/positions.py`:** ortalama maliyetli pozisyon defteri (kısmi kapanış, yön değişimi,
  temel varlıkla ödenen komisyon, funding), kalıcı.
- **`execution/engine.py`: işlem motoru.**
  - Futures: giriş + borsa tarafında zarar durdur (`closePosition`), kademeli hedefler
    (`reduceOnly`), iz süren stop. Spot: hedef başına OCO (hedef + stop), kalan miktar için stop.
  - İlk hedef dolunca stop giriş fiyatına çekilir. Pozisyon kapanınca kalan koruma emirleri
    iptal edilir.
  - Yuvarlama: stop hiçbir zaman istenenden uzağa, hedef hiçbir zaman istenenden uzağa
    yuvarlanmaz.
  - Her işlem bir karar kaydına bağlıdır ("neden açıldı"). Motor yeniden başladığında açık
    pozisyonların yönetimi bu kayıttan geri kurulur.
- **`execution/binance_venue.py`: Binance yürütücüleri** (2026-11 kuralları):
  - Futures koşullu emirler Algo servisinde (`/fapi/v1/algoOrder`); eski uç nokta bunları
    -4120 ile reddeder.
  - Futures kullanıcı akışı `listenKey` + `/private/ws/<listenKey>`.
  - Spot kullanıcı akışı WebSocket API `userDataStream.subscribe.signature` ile (REST listenKey
    2026-02-20'de kaldırıldı). İmzadan önce yüzde-kodlama.
- **`execution/reconcile.py`: mutabakat.** Akış kopunca, açılışta ve dakikada bir çalışır.
  Borsa tek doğru kaynaktır:
  - açık emir durumları ve kaçırılan dolumlar düzeltilir;
  - pozisyon/bakiye farkı **kritik** olay olarak yazılır;
  - stopu kaybolmuş pozisyonun koruması yeniden kurulur;
  - kapanmış pozisyonun artık koruma emirleri iptal edilir;
  - kullanıcının elle verdiği emir ve pozisyonlara **dokunulmaz** (yalnızca raporlanır).
- **`security/exchange_keys.py`: anahtar saklama.**
  - Yalnızca **test ağı** anahtarı kabul edilir. Anahtar önce salt-okunur imzalı istekle
    doğrulanır, sonra şifreli kasaya yazılır.
  - Yanıtlarda ve denetim kaydında yalnızca son 4 karakter görünür.
  - Canlı anahtar için (G1 sonrası) `apiRestrictions` denetimi hazır ve test edildi: para
    çekme veya transfer yetkisi açıksa ret.
- **`execution/service.py` + yerel API `/v1/execution/*`:** test ağı anahtarı, bağlantı, işlem
  açma/kapama, pozisyonlar, emirler, acil kapatma, elle mutabakat.
  - İşlem açmak için işlem modu TESTNET olmalı.
  - Zarar durdur zorunludur ve doğru tarafta olmalıdır. Kaldıraç ayardaki üst sınırı aşamaz.
- **Gerçek hesap kilidi (G1/G2):** üç bağımsız katman.
  1. LIVE mod kontrolü her zaman başarısız.
  2. Binance yürütücüsü LIVE modda kurulamaz.
  3. Canlı anahtar kasaya yazılamaz.

  Ayrıca test ağı modunda gerçek Binance adreslerine bağlanma reddedilir.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Uçtan uca senaryolar (giriş, stop, kademeli hedef, başa baş, iz süren stop, OCO, elle kapatma) | ✅ Sanal yürütücüyle 16 test. Ayrıca 2026 kurallarını taklit eden sahte Binance sunucusuna karşı **gerçek HTTP/WebSocket** ile 14 test: imza doğrulaması, Algo servisi, -4120, iki kullanıcı akışı, futures ve spot motor uçtan uca |
| İdempotentlik (çift emir yok) | ✅ "Emir borsaya ulaştı ama yanıt 503/-1007" senaryosunda emir tek kez gönderildi, durum istemci kimliğiyle sorgulandı. "Ulaşmadı" senaryosunda aynı kimlikle yeniden denendi |
| Emir gerçekleşme doğrulaması / mutabakat | ✅ 8 test. Motor kapalıyken tetiklenen stop: açılışta dolum alındı, pozisyon kapandı, kalan hedefler iptal edildi. Akış koparken tetiklenen stop: yeniden bağlanınca mutabakat çalıştı. Kaybolan stop yeniden kuruldu; ilk hedeften sonra başa baş stopla ve yeni kimliklerle kuruldu. Pozisyon/bakiye farkı kritik olay olarak yazıldı |
| API anahtar politikası | ✅ Para çekme yetkisi açık veya bilinmiyorsa ret. Canlı anahtar saklama reddi. Yanlış gizli anahtar saklanmıyor. Anahtar yanıtlarda, denetim kaydında ve veritabanı dosyasında düz metin olarak bulunmuyor (testle) |
| Gerçek Binance test ağı | ⚠️ Kısmen. Futures test ağı: kullanılan tüm uç noktalar mevcut (anahtar istiyor; bilinmeyen yol 404), 699 USDT sembolünün kuralları ayrıştırıldı, saat farkı 112 ms, `/private` akışı bağlantı kabul ediyor. **Anahtarla emir denemesi yapılamadı:** test ağı anahtarı verilmedi. Spot test ağı bu test ortamından coğrafi kısıtlama (HTTP 451) nedeniyle denenemedi |
| G1/G2 olmadan LIVE açılmaz | ✅ Üç bağımsız katman testle doğrulandı |

**Test ağı anahtarıyla ilk denemede doğrulanacaklar (belgelerden kesinleştirilemedi):**

1. `ALGO_UPDATE` olayının alan adları. Bu olay yalnızca tetikleyici olarak kullanılıyor; gerçek
   durum belgelenmiş REST sorgusundan alınıyor.
2. Spot OCO parametre adları (`aboveType`, `belowStopPrice` vb.).
3. Futures test ağı `/private` akışının olay iletimi.
4. Test ağındaki gerçek dolum akışı.

Tüm adresler ayarlardan değiştirilebilir. Not: test ağında BTCUSDT en düşük emir değeri
50 USDT'dir.

### Aşama 11 — Risk yönetimi ✅

**Çıktılar (uygulandı):**

- **`risk/gate.py`: risk kapısı.** İşlem açılmadan önce bağımsız denetim. Kurallar:
  - Motor durumu RUNNING ve işlem modu yürütücüyle aynı olmalı.
  - Zarar durdur zorunlu ve doğru tarafta olmalı.
  - Fiyat, işlemin yapılacağı yerden (test ağı) okunur; sinyalden %1'den fazla sapmışsa ret.
  - Hesap bilgisi borsadan okunamazsa ret.
  - İşlem başına risk: stopta kayıp + iki yön komisyon + kayma payı, özsermayenin %0,5'ini
    aşamaz.
  - Günlük zarar bütçesi: bugünkü kayıp + bu işlemin riski günlük sınırı (%2) aşamaz. Gün
    kilitliyse ret.
  - En fazla 3 açık pozisyon. Eşzamanlı açılışlar sınırı birlikte aşamaz.
  - Kaldıraç ≤ 3x (verilmezse 1x; motor kaldıracı her zaman açıkça ayarlar). Toplam pozisyon ≤
    özsermayenin 3 katı. Spot'ta kaldıraç yok.
  - Tahmini tasfiye uzaklığı ≥ %15 (ayrık ve çapraz tahminin kötüsü). Stop tasfiye fiyatından
    önce olmalı.

  Tüm sınırlar ayarlardan değiştirilebilir ama kodda üst sınırları vardır (işlem başına en
  fazla %5, günlük en fazla %20, kaldıraç en fazla 20x).
- **Tek kapı (`execution/approval.py`).** Onaylanan işleme kapı **imzalı, 60 sn geçerli, tek
  kullanımlık** bir onay verir. Emir yöneticisi giriş emrini bu onay olmadan göndermez.
  Onaysız gönderilebilen emirler riski artıramaz: Futures'ta `reduceOnly`/`closePosition`
  zorunlu; Spot'ta yalnızca satış. Emir yöneticisi ve işlem motoru risk kapısı olmadan
  kurulamaz.
- **`risk/account.py`: hesap izleyici.** Özsermaye borsadan okunur: cüzdan + gerçekleşmemiş
  kâr/zarar. Gün başı özsermaye UTC gününün ilk ölçümünde `risk_daily` tablosuna yazılır;
  motorun yeniden başlatılması günlük zarar sayacını sıfırlamaz.
- **`risk/guard.py`: risk bekçisi.** Ayrı görevde, 5 sn'de bir çalışır:
  - Günlük zarar sınırında gün kilitlenir. Motor güvenli moda iner ve UTC gün sonuna kadar
    yeni işlem açılmaz (özsermaye toparlansa da). Pozisyonların kapatılması da istenebilir;
    varsayılan: kapatma, borsadaki stoplar yerinde kalır.
  - Kullanıcı akışı 30 sn'den uzun koparsa güvenli mod.
  - Mutabakatta kritik fark varsa güvenli mod.
  - Stopu olmayan pozisyonda kritik olay yazılır ve koruma yeniden kurulur.
  - Tasfiye fiyatı %15'ten yakınsa uyarı; %5'ten yakınsa pozisyon acil kapatılır.
- **`execution/auto.py`: otomatik işlem.** Eşik üstü fırsat sinyallerini **test ağında**
  işleme çevirir. Varsayılan **kapalı**.
  - Test ağı fiyatı gerçek piyasadan farklı olduğu için sinyalin stop/hedef **uzaklıkları**
    test ağı fiyatına uygulanır.
  - Miktar riske göre hesaplanır (varsayılan %0,25). Hedef uzaksa yarısı 1R'de alınır, sonra
    stop girişe çekilir.
  - Saatlik giriş sınırı ve sembol bekleme süresi vardır. Aynı sinyal iki kez işleme dönmez.
- **Karar günlüğü:** her niyet için kapının kararı, gerekçeleri ve ölçümleri `decisions`
  tablosunda; retler ayrıca `risk_events`'te.
- **Yerel API:** `/v1/risk/status|events|decisions`, `/v1/autotrade` (aç/kapat, durum).

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Her kural için ret testi | ✅ 17 kuralın her biri ayrı testle reddediliyor. Ret kaydı (karar + gerekçe + olay) ve "ret sonrası hiçbir emir, kaldıraç ayarı bile gönderilmedi" testle doğrulandı |
| Risk kapısını atlayan kod yolu olmadığı | ✅ Çalışma anında: onaysız, sahte imzalı, süresi dolmuş, tekrar kullanılan, başka sembol/yön/piyasa için veya fazla miktarlı onayla giriş emri reddediliyor (7 deneme, borsaya 0 emir). Onaysız emirlerin riski artıramadığı test edildi. Statik: kaynak kodda borsaya emir gönderen tek dosya emir yöneticisi; emir yöneticisi ve işlem motoru risk kapısı olmadan kurulamıyor |
| Günlük zarar sınırında otomatik durma | ✅ %2,1 kayıpta güvenli mod, kritik olay ve uyarı. Özsermaye toparlansa da gün kilitli kaldı; kilit yeniden başlatmada da korundu; yeni UTC gününde kalktı |
| Bağlantı kesintisinde güvenli mod | ✅ Kullanıcı akışı tolerans süresinden uzun kopunca güvenli mod; bağlanınca geri döndü. Mutabakatta kritik pozisyon farkı olunca güvenli mod; bilinmeyen (kullanıcının) pozisyonu yalnızca uyarı |
| Otomatik işlem | ✅ Sahte borsada: sinyal riske göre boyutlandı (116,279 BTC = 250 USDT risk), uzaklıklar test ağı fiyatına uygulandı, stop ve kademeli hedefler borsaya kondu. Uygunsuz sinyal (düşük puan, eski, seviyesiz, yanlış piyasa, test ağında olmayan sembol) atlandı. Kapalıyken veya mod TESTNET değilken işlem yok |

**Not:** Risk kapısı kayıpları **sınırlar**, kârı garanti etmez. Test ağı sonuçları gerçek
piyasa sonuçlarını göstermez (likidite ve fiyatlar farklıdır).

### Aşama 12 — Windows EXE ✅ (imzasız; kod imzalama G6, otomatik güncelleme G5 bekliyor)

**Çıktılar (uygulandı):**

- **Arayüz (`desktop/src`, React + TypeScript).** 10 ekran:
  - **Genel bakış:** motor durumu, acil durdurma, bot başlat/durdur, hazırlık koşulları, en iyi
    fırsatlar, balina uyarıları.
  - **Piyasa:** tüm coinler; arama, sıralama, fonlama oranı; anormal hareketler; tarayıcı
    sinyalleri.
  - **Fırsatlar:** puan bileşenleri, cezalar, maliyet.
  - **Balina radarı:** net akış, büyük işlemler, uyarılar, büyük hesapların konumlanması.
  - **Grafik ve AI analiz:** TradingView Lightweight Charts mum grafiği; destek/direnç ve trend
    çizgileri; model tahmini; göstergeler.
  - **Spot/Futures işlemler:** test ağı pozisyonları, borsadaki emirler, zorunlu stoplu işlem
    formu, kapatma, tümünü kapatma.
  - **Kâr/zarar ve geçmiş:** strateji yarışması, sanal pozisyonlar, işlem geçmişi, test ağı
    emirleri.
  - **Risk:** sınırlar, karar günlüğü (neden açıldı / açılmadı), risk olayları.
  - **Strateji performansı.**
  - **Ayarlar:** işlem modu, test ağı anahtarı, denetim kaydı.

  Canlı uyarılar olay akışından bildirim olarak gelir. Tipler paylaşılan protokol şemasından
  üretilir; CI şemanın güncel olduğunu denetler.
- **Kabuk (`desktop/src-tauri`, Rust).**
  - Motoru başlatır ve oturum belirtecini üretir (diske yazılmaz).
  - Sağlık denetimini bekler; motor çökerse yeniden başlatır.
  - Kapanışta düzgün kapatma ister.
  - Windows iş nesnesiyle sahipsiz motor kalmaz.
  - Tek örnek çalışır. CSP yalnızca 127.0.0.1'e izin verir.
- **Motor paketleme (`engine/packaging`).** PyInstaller, tek klasör. Açılış ~2 sn.
- **Kurulum paketi:** NSIS, kullanıcı başına, yönetici yetkisi istemez, Türkçe.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| E2E arayüz testleri | ✅ 8 Playwright senaryosu, gerçek motor + sahte Binance (piyasa verisi ve test ağı borsası). Kapsam: tüm ekranlar açılıyor; canlı fiyat listesi ve arama; acil durdurma ve onay ifadesiyle kaldırma; gerçek hesap düğmesi kilitli; yanlış anahtar saklanmıyor, doğru anahtar doğrulanıp bağlanıyor, gizli anahtar ekranda kalmıyor; stopsuz işlem risk kapısınca reddediliyor; korumalı işlem açılıp 3 koruma emriyle görünüyor ve kapatılıyor; karar günlüğü; bot aç/kapa. Ayrıca 13 birim testi (biçimlendirme, bağlantı güvenliği, API istemcisi) ve 3 Rust testi |
| Temiz Windows makinesinde kurulum testi | ✅ İlk CI çalışmasında geçti (GitHub windows-latest). Paketlenmiş motor duman testinden geçti. Sessiz kurulum `%LOCALAPPDATA%\AI Trading Intelligence` dizinine yapıldı. Uygulama açılınca motor ~6 sn'de yanıt verdi. Kabuk zorla kapatılınca motor da kapandı (iş nesnesi). Sessiz kaldırma tamamlandı. İmzasız kurulum paketi ~79 MB, CI çıktısı olarak indirilebilir |
| Kod imzalama | ⏸️ G6 onayı bekleniyor (sertifika). Paket imzasız |
| Otomatik güncelleme | ⏸️ Güncelleme sunucusu (G5) ile birlikte |

**Uçtan uca testte bulunan ve düzeltilen gerçek hata:** form işlemleri ilk çizimdeki değerleri
gönderiyordu. Bu yüzden anahtar formu boş alanla gidiyordu; motor bunu doğru biçimde reddetti.
Düzeltildi ve testle doğrulandı.

**Not:** Paketlenmiş motor ~320 MB'tır (DuckDB, SciPy, ONNX Runtime, NumPy, LightGBM); kurulum
paketi sıkıştırılmıştır.

### Aşama 13 — iOS uygulaması ✅ (kod ve testler; cihaza kurulum G6, bulut dağıtımı G5 bekliyor)

**Çıktılar (uygulandı):**

- **Protokol (`shared/protocol/remote-v1.md`).**
  - Telefon ↔ aktarma servisi ↔ motor arasında uçtan uca imzalı mesajlar.
  - Telefonda iki P-256 anahtarı (Secure Enclave), motorda Ed25519 anahtarı.
  - İmza, gönderilen metnin kendisi üzerine atılır; diller arası kanonikleştirme gerekmez.
  - Ortak test vektörleri (`test-vectors/remote-v1.json`): Python üretir, Swift doğrular.
- **Motor (`engine/src/ati_engine/remote`).**
  - Eşleştirme: tek kullanımlık, 5 dakikalık QR gizli değeri. HMAC kanıtı sayesinde aktarma
    servisi cihaz ekleyemez.
  - Komut doğrulama sırası: biçim → motor kimliği → kayıtlı/iptal edilmemiş cihaz → imza →
    zaman farkı → kalıcı sıra numarası (tekrar oynatma) → izin listesi → korumalı anahtar.
  - Face ID gerektiren komutlar ayrı, biyometrik erişim denetimli anahtarla imzalanır. Kanıt
    donanıma dayanır.
  - Motor mesajları imzalıdır ve yalnızca eşleştirilmiş cihazlara tek tek gönderilir.
  - Masaüstünde QR ile eşleştirme, cihaz listesi ve eşleştirme kaldırma, uzaktan komut kaydı.
- **Aktarma servisi (`cloud/src/ati_cloud/relay.py`).**
  - Anahtar tutmaz. Bağlanan tarafın kimliğini imzalı `hello` ile doğrular.
  - Kanalları yalıtır. Hız sınırı ve motor başına 20 telefon sınırı vardır.
- **iOS uygulaması (`ios/`).**
  - `ATICore` Swift paketi: protokol, imza, doğrulama, oturum denetleyicisi, motor benzetimi.
    Linux'ta da test edilir.
  - SwiftUI uygulaması:
    - eşleştirme (QR okuyucu veya yapıştırma);
    - özet (motor durumu, günlük zarar, sanal K/Z);
    - acil durdurma (tek dokunuş) ve bot başlat/durdur;
    - pozisyonlar ve kapatma (Face ID);
    - fırsatlar ve balina hareketleri;
    - bildirim merkezi (uygulama arka plandayken yerel bildirim);
    - ayarlar (doğrulanamayan mesaj sayacı, eşleştirmeyi kaldırma).
  - Anahtarlar Secure Enclave'de; korumalı anahtar `.biometryCurrentSet` ile üretilir.
- **Uzaktan asla yapılamayanlar:** para çekme, yeni pozisyon açma, risk sınırı değiştirme,
  API anahtarı girme, işlem modu değiştirme.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| İmzasız/tekrar oynatılmış komutun reddi | ✅ Motor (Python, 21 test): imzasız, çöp imza, başka anahtar, değiştirilmiş içerik, eski/ileri tarihli, başka motora ait, eski sıra numarası, izin dışı komut, Face ID'siz korumalı komut ve başka cihaz adına yönlendirme reddediliyor; hiçbiri uygulanmıyor. Sıra numarası yeniden başlatmada korunuyor; eşzamanlı 5 kopyadan yalnızca biri uygulanıyor |
| Gerçek aktarma servisiyle uçtan uca | ✅ Ayrı süreçte gerçek aktarma servisi, gerçek motor ve telefon benzetimi. Eşleştirme, imzalı acil durdurma, tekrar oynatmanın reddi, imzasızın yanıtsız kalması, Face ID'siz kaldırmanın reddi, başka cihaz adına gönderimin reddi, korumalı anahtarla kaldırma, eşleştirme kaldırılınca reddi doğrulandı. Aktarma servisi testleri (10): kimlik kanıtı, kanal yalıtımı, hız ve cihaz sınırı |
| XCTest | ✅ `ATICore`, 23 test, Linux'ta Swift 6.4 ile geçti. Kapsam: Python'un imzaladığı mesajın doğrulanması ve değiştirilmişin reddi; aynı anahtardan aynı kimlik; HMAC kanıtı ve hello metninin motorla eşleşmesi; eski özetin ve başka cihaza ait mesajın yok sayılması; denetleyici akışları (eşleştirme, imzalı komut, iptal edilen Face ID'de hiçbir şey gönderilmemesi, sahte mesajın yok sayılması, tekrar oynatmanın reddi). macOS'ta CryptoKit ile CI'da çalışır |
| Arayüz testleri (XCUITest) | ✅ 5/5 senaryo macOS CI'da (Xcode 16, iOS simülatörü) geçti: eşleştirme, acil durdurma, onaylı pozisyon kapatma, aktarma servisinden gelen sahte mesajın yok sayılması, bot başlatma ve eşleştirme kaldırma |
| Cihaza kurulum, TestFlight, App Store | ⏸️ Apple Developer hesabı (G6) |
| Uygulama kapalıyken anlık bildirim (APNs) | ⏸️ Bulut dağıtımı (G5) ve Apple hesabı (G6) |
| Hesap girişi ve lisans ekranı | ⏸️ Bulut hesap/lisans API'si Aşama 15'te; iOS ekranı o zaman bağlanacak |

**Gizlilik notu:** mesajlar imzalıdır ama şifreli değildir. Aktarma servisi özet içeriğini
görebilir; hassas veri gönderilmez. Uçtan uca şifreleme Aşama 18'de.

### Aşama 14 — Web sitesi ✅ (kod ve testler; yasal metinler hukukçu onayı, dağıtım G5, ödeme G3 bekliyor)

**Çıktılar (uygulandı):**

- **Hesap API'si (`cloud/src/ati_cloud/accounts.py`).**
  - Kayıt, e-posta doğrulama (ve bağlantıyı yeniden gönderme), giriş/çıkış, parola sıfırlama,
    müşteri paneli (`/v1/me`), satıştaki paketler (`/v1/plans`).
  - Parolalar Argon2id ile özetlenir. Var olmayan kullanıcıda da aynı doğrulama süresi harcanır.
  - Oturum: 256 bitlik belirteç `HttpOnly; Secure; SameSite=Strict` çerezde. Veritabanında
    yalnızca SHA-256 özeti tutulur. Doğrulama/sıfırlama belirteçleri tek kullanımlıktır.
  - Kayıt, sıfırlama ve yeniden gönderme, adresin kayıtlı olup olmadığını açığa vurmaz.
  - Durum değiştiren her istekte `Origin` denetimi (CSRF), IP ve e-posta başına hız sınırı.
  - Parola sıfırlanınca tüm oturumlar kapatılır. Olaylar hash zincirli denetim kaydına yazılır.
- **İletişim formu (`cloud/src/ati_cloud/contact.py`, geçiş `0003`).** Mesaj veritabanına
  yazılır, gönderene otomatik e-posta gitmez (form spam aracı olarak kullanılamaz). Bot tuzağı
  alanı ve hız sınırı vardır.
- **API sunucusu (`ati-cloud-api`).** İstemci IP'si yalnızca güvenilen vekillerden gelen
  `X-Forwarded-For` ile çözülür.
- **Web sitesi (`web/`, Next.js 16 App Router, TypeScript, Tailwind 4).**
  - Sayfalar: ana sayfa, özellikler, paketler, satın alma, giriş, kayıt, e-posta doğrulama,
    parola sıfırlama, müşteri paneli, SSS, iletişim, kullanım koşulları, gizlilik/KVKK, risk
    bildirimi.
  - Paketler API'den gelir. Fiyat girilmemişse "yakında" gösterilir; satın alma düğmesi
    ödeme sistemi (Aşama 17, G3) açılana kadar kapalıdır.
  - Güvenlik: her istekte yeni nonce'lu CSP (satır içi betik yok), çerçeveleme yasak,
    `nosniff`, `Referrer-Policy`, `Permissions-Policy`, üretimde HSTS. Doğrulama ve sıfırlama
    belirteçleri adres çubuğundan silinir. Giriş sonrası yönlendirme yalnızca site içine.
  - İçerik kuralı: hiçbir sayfada kazanç vaadi yok (otomatik test). Her sayfada risk uyarısı.
  - Modern tasarım: sistem yazı tipleri (Segoe UI Variable / SF Pro; indirme yok, ilk görüntü
    gecikmez), ikonlar, ızgara ve ışık efektli başlıklar, örnek arayüz görselleri (kazanç rakamı içermez, "örnek" olarak
    etiketli), platform bölümü (Windows + iPhone).
  - Açık/koyu tema, klavye ile tam kullanım, "içeriğe geç" bağlantısı, etkin sayfa işareti
    (`aria-current`), sayfa değişince ve Escape ile kapanan mobil menü, hareket azaltma tercihi.
  - Alan adı `canarslan.net.tr`; üretim adresleri ve ayar örnekleri [`deploy/`](../deploy/)
    altında. Bulut servisi staging/üretimde HTTPS olmayan site adresini ve kökeni reddeder.
  - Yasal metinler "Taslak — hukukçu onayı bekliyor" olarak işaretli; şirket bilgileri köşeli
    parantezle bırakıldı.

**Kabul kriterleri ve sonuçlar:**

| Kriter | Sonuç |
|---|---|
| Hesap API'si | ✅ 19 test (gerçek PostgreSQL): kayıt/doğrulama/giriş/panel/çıkış, yanlış parola ile bilinmeyen e-postanın aynı yanıtı, kayıtta hesap sızdırmama, zayıf parolalar, koşul onayı, yabancı kökenin reddi, giriş hız sınırı, parola sıfırlamanın oturumları kapatması, engelli müşteri, yalnızca satıştaki paketler, panelde lisans ve cihaz sayısı, iletişim formu (tuzak, sınır, köken), doğrulama bağlantısını yeniden gönderme. Bulut toplamı 84 test |
| Birim testleri | ✅ 29 test (vitest): açık yönlendirme koruması, fiyat/tarih biçimi, API hata çevirisi, CSP, içerik kuralı, paket gruplama, ayarlar |
| Uçtan uca | ✅ 22 senaryo (Playwright, gerçek API + PostgreSQL + derlenmiş site): tüm herkese açık sayfalarda güvenlik başlıkları, CSP ihlali ve konsol hatası olmaması, tek `h1`, risk uyarısı, kazanç vaadi olmaması; kayıt → doğrulama bağlantısını yeniden isteme → doğrulama → giriş → panel → çıkış; panelde lisans; parola sıfırlama; açık yönlendirme denemesi; paketler ve kapalı ödeme; iletişim formu; çerezin `HttpOnly`/`SameSite=Strict` ve JavaScript'e kapalı olması |
| Erişilebilirlik denetimi | ✅ axe (WCAG 2.1 AA + en iyi uygulamalar): 10 herkese açık sayfa açık ve koyu temada, mobil menü ve müşteri paneli — 0 ihlal |
| Performans denetimi | ✅ Lighthouse (mobil öykünme): 10 sayfada performans 97-99, erişilebilirlik 100, en iyi uygulamalar 100, SEO 100 (CI eşikleri: 90 / 100 / 95 / 95; her sayfa 3 kez ölçülür, ortanca sonuç esas alınır) |
| Yasal metinlerin hukukçu onayı | ⏸️ Kullanım koşulları, gizlilik/KVKK ve risk bildirimi taslak; şirket bilgileri ve hukukçu onayı bekliyor. Mesafeli satış sözleşmesi ve ön bilgilendirme formu Aşama 17'de |
| Yayına alma (alan adı, TLS, e-posta gönderimi) | ⏸️ G5 |

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

1. **Fiyatlandırma:** ✅ Karar: paketler (fiyat, para birimi, satışa açma/kapama) ve ödeme
   bilgileri **admin panelinden** yönetilecek (Aşama 16-17). Panel hazır olana kadar paketler
   pasif ve fiyatsızdır; site "yakında" gösterir.
2. **iOS cihaz politikası:** Şu an varsayılan: cihaz limiti (1/2/3) Windows motorları için,
   iOS eşlikçi cihazlar ayrıca 2 adet. iOS'un da limite sayılmasını isterseniz
   `companion_device_limit` ayarlanır.
3. **Ödeme sağlayıcısı** (bkz. `02` — Paddle/Lemon Squeezy, Stripe, iyzico/PayTR). Sağlayıcı
   anahtarları admin panelinden şifreli olarak girilecek; canlı moda geçiş G3 onayıyla.
4. **Hedef pazarlar ve dil:** Türkçe + İngilizce önerilir.
5. **Şirket ve faturalama:** e-Arşiv/e-Fatura entegratörü.
6. **Bulut sağlayıcısı ve veri bölgesi** (KVKK kapsamında yurt dışına veri aktarımı
   değerlendirilmeli). Alan adı: ✅ `canarslan.net.tr`.

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
