# ati-engine — Yerel İşlem Motoru

AI Trading Intelligence'ın kullanıcının Windows bilgisayarında çalışan işlem motoru.
Mimari için bkz. [`../docs/01-sistem-mimarisi.md`](../docs/01-sistem-mimarisi.md).

## Geliştirme

```bash
cd engine
uv sync                      # bağımlılıklar + geliştirme araçları
uv run pytest                # testler
uv run ruff check . && uv run ruff format --check .
uv run mypy                  # sıkı tip denetimi
```

## Çalıştırma

```bash
uv run ati-engine run --data-dir ./.data --port 0
uv run ati-engine show-config
uv run ati-engine verify-audit --data-dir ./.data
uv run ati-engine export-protocol-schema --output ../shared/protocol/engine-local-api.schema.json
```

## Piyasa verisi (Aşama 2)

Motor açılışta Binance Spot ve USDⓈ-M Futures'taki tüm işlem gören USDT paritelerini keşfeder
ve herkese açık WebSocket akışlarına bağlanır (API anahtarı gerekmez). Piyasa verisi hazır
olana kadar motor **güvenli modda** (SAFE_MODE) bekler; bağlantı koparsa yine güvenli moda iner.

```toml
# config.toml örneği
[market_data]
enabled = true
kline_intervals = ["1m"]
include_agg_trades = true
streams_per_connection = 200
focus_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]  # yerel emir defteri
# symbol_allowlist = ["BTCUSDT", "ETHUSDT"]   # düşük donanımlı bilgisayarlar için evreni daralt
```

Yerel API: `GET /v1/market/status`, `GET /v1/market/tickers?market=spot&limit=50`,
`POST /v1/market/focus` (`{"market": "spot", "symbols": ["BTCUSDT"]}`).

Gerçek veriyle dayanıklılık testi (veri kaybı, yeniden senkron, gecikme ölçümü):

```bash
uv run python scripts/live_soak.py --seconds 600 --report soak.json --verbose
```

## Tarihsel veri ve grafik analizi (Aşama 5)

Binance'in herkese açık arşivinden (`data.binance.vision`) sembolün listelendiği günden bugüne
mumları indirir ve her dosyayı SHA-256 ile doğrular. Arşivin kapsamadığı dönemler herkese açık
REST ile tamamlanır:
- arşivden önce listelenmiş sembollerin ilk günleri,
- bugünün kapanmış mumları,
- arşivde eksik kalan günler.

Veriler `market/history.duckdb` dosyasındadır. Sonraki çalıştırmalarda yalnızca yeni veri
alınır.

```bash
# Motor kapalıyken (motor çalışırken dosya kilitlidir; API'yi kullanın)
uv run ati-engine history-sync --market spot --symbol BTCUSDT ETHUSDT --interval 1h
# Balina radarını son 30 günün işlem arşivi üzerinde yeniden oynat (etki doğrulaması)
uv run ati-engine history-replay --market usdm_futures --symbol BTCUSDT --days 30
```

Yerel API:
- `GET /v1/history/status`
- `POST /v1/history/sync` (`{"market": "spot", "symbols": ["BTCUSDT"], "interval": "1h"}`)
- `GET /v1/history/candles?symbol=BTCUSDT&interval=4h&bars=500`: depoda yoksa 1 dakikalıktan
  üretilir.
- `GET /v1/history/levels?...`: destek/direnç.
- `GET /v1/history/trend?...`: aktif trend çizgileri ve kırılımlar.
- `GET /v1/history/similar?symbol=BTCUSDT&window=48&horizons=6,24`: benzer geçmiş dönemler ve
  sonrasındaki hareket.

Benzerlik ve etki istatistikleri geçmişi anlatır; gelecekteki fiyatı **garanti etmez**.

## Emir yürütme — Binance test ağı (Aşama 10)

**Gerçek hesapla işlem bu sürümde kilitlidir.** Açılması için kullanıcının açık onayları
gerekir: G1 (işlem yetkili, para çekme yetkisi KAPALI canlı anahtar) ve G2 (ilk gerçek para
işlemi). Bu sürümde yalnızca sanal işlem (PAPER) ve Binance **test ağı** (TESTNET) çalışır.

Test ağında denemek için:

1. testnet.binancefuture.com (futures) veya testnet.binance.vision (spot) üzerinden test ağı
   API anahtarı oluşturun. Test ağı parası gerçek değildir.
2. `POST /v1/execution/testnet-key` ile anahtarı girin
   (`{"market": "usdm_futures", "api_key": "...", "secret": "..."}`). Anahtar önce salt-okunur
   bir istekle doğrulanır, sonra şifreli kasaya yazılır; yanıtta yalnızca son 4 karakter görünür.
3. `POST /v1/trading-mode {"mode": "testnet"}` ile işlem modunu değiştirin.
4. `POST /v1/execution/trades` ile işlem açın. Zarar durdur zorunludur.
   - Futures: zarar durdur (`closePosition`), kademeli hedefler, isteğe bağlı iz süren stop;
     hepsi borsa tarafında Algo emirleri olarak.
   - Spot: hedef başına OCO.
   - İlk hedef dolunca stop giriş fiyatına çekilir.

Diğer uç noktalar:
- `GET /v1/execution/status|positions|orders`
- `POST /v1/execution/close`, `POST /v1/execution/close-all`
- `POST /v1/execution/reconcile?market=`

Mutabakat akış kopunca, açılışta ve dakikada bir çalışır. Borsa tek doğru kaynaktır:
kaçırılan dolumlar alınır, kaybolan stop yeniden kurulur, pozisyon farkı kritik olay olarak
yazılır. Kullanıcının elle verdiği emirlere dokunulmaz.

## Risk yönetimi ve otomatik işlem (Aşama 11)

Her işlem açılmadan önce **risk kapısından** geçer. Kapı onaylamazsa hiçbir emir gönderilmez;
karar ve gerekçeleri kaydedilir (`GET /v1/risk/decisions`). Varsayılan sınırlar:

| Sınır | Varsayılan | Ayar (`[risk]`) |
|---|---|---|
| İşlem başına risk (stop + komisyon + kayma) | özsermayenin %0,5'i | `max_risk_per_trade_pct` |
| Günlük zarar (gerçekleşmiş + gerçekleşmemiş) | %2 → gün kilitlenir | `max_daily_loss_pct` |
| Açık pozisyon | 3 | `max_open_positions` |
| Kaldıraç / toplam pozisyon | 3x / özsermayenin 3 katı | `max_leverage`, `max_total_leverage` |
| Tasfiye uzaklığı | en az %15 | `min_liquidation_distance_pct` |
| Sinyalden fiyat sapması | en fazla %1 | `max_price_deviation_pct` |

Zarar durdur zorunludur. Giriş emri, kapının verdiği imzalı ve tek kullanımlık onay olmadan
borsaya gönderilemez.

**Risk bekçisi** ayrı çalışır:
- günlük zarar sınırında UTC gün sonuna kadar yeni işlemi durdurur;
- kullanıcı akışı koparsa veya mutabakatta kritik fark varsa motoru güvenli moda alır;
- stopu kaybolan pozisyonun korumasını yeniden kurar;
- tasfiyeye çok yaklaşan pozisyonu kapatır.

Durum: `GET /v1/risk/status`, olaylar: `GET /v1/risk/events`.

**Otomatik işlem** (yalnızca test ağı, varsayılan kapalı): `POST /v1/autotrade {"enabled": true}`.
Eşik üstü fırsat sinyalleri riske göre boyutlanır ve sinyalin stop/hedef uzaklıkları test ağı
fiyatına uygulanır. Hedef uzaksa yarısı 1R'de alınır. İşlem modu TESTNET olmalıdır.
Sonuçlar garanti değildir; test ağı gerçek piyasayı birebir yansıtmaz.

## Sanal işlem yarışması (Aşama 9)

Her strateji ve fırsat puanı, her piyasa için **ayrı bir sanal hesapla** (varsayılan 10.000
USDT, işlem başına %1 risk) aynı canlı veriyi bağımsız olarak değerlendirir. Gerçek borsaya
**hiçbir emir gönderilmez**.

- **Giriş:** saatlik mum kapandığında en güçlü sinyaller boş yuvalara açılır.
  - Dolum: odak sembollerinde gerçek emir defteri seviye seviye tüketilerek, diğerlerinde
    likiditeye göre tahmini spread + kayma ile simüle edilir.
  - Likiditesi düşük (24 saatlik hacim < 20 milyon USDT) semboller elenir.
  - Zarar durdur uzaklığı maliyetin altında kalan veya hedefi maliyeti 2 kat karşılamayan
    işlemler açılmaz.
- **Çıkış:** zarar durdur/hedef her canlı işlemde (tick düzeyinde) denetlenir; ayrıca süre ve
  ters sinyal. Vadelide funding 00/08/16 UTC'de uygulanır.
- **Eksik mum:** motor mumun ortasında başlarsa veya bağlantı koparsa eksik toplanan mum
  stratejilere verilmez; kapanmış aslı REST'ten alınır.
- **Kalıcılık:** hesaplar, pozisyonlar ve işlemler veritabanındadır; yeniden başlatınca
  yarışma kaldığı yerden sürer.
- **Terfi hattı:** `walk_forward` → `paper` → (30 gün, 30 işlem, PF ≥ 1,1, Sharpe ≥ 0,5,
  düşüş ≤ %20) → `live_candidate`. **`live` aşamasına otomatik geçiş yoktur.**

Yerel API:
- `GET /v1/paper/leaderboard?market=usdm_futures`
- `GET /v1/paper/positions`, `GET /v1/paper/trades`, `GET /v1/paper/stats`
- Olay: `PaperTradeEvent` (açıldı/kapandı)

## Backtest (Aşama 8)

Stratejiler, puan eşikleri ve al-ve-tut aynı geçmiş üzerinde canlıdakiyle aynı kodla sınanır.
- **Maliyetler:** komisyon, spread, kayma ve funding.
- **Tasfiye:** vadelide modellenir.
- **İleriye bakma yok:** sinyal mum kapanışında, emir sonraki açılışta.
- **Doğrulama:** yürüyen pencere (parametre geçmişte seçilip gelecekte sınanır) ve arındırılmış
  çapraz doğrulama (aşırı uyum olasılığı, PBO).

```bash
uv run ati-engine backtest --symbol BTCUSDT ETHUSDT --since 2021-01-01
uv run ati-engine backtest --market usdm_futures --symbol BTCUSDT ETHUSDT --since 2021-01-01
```

Raporlar `backtests/` dizinine yazılır; sonuçlar strateji kayıt defterine (`/v1/strategies`)
işlenir. Örneklem dışı ölçütleri karşılayan strateji `walk_forward` aşamasına geçer. **Canlı
aşamaya otomatik geçiş yoktur.**

Yerel API:
- `POST /v1/backtest/run`, `GET /v1/backtest/jobs`
- `GET /v1/backtest/reports`, `GET /v1/backtest/reports/{ad}`
- `GET /v1/strategies`

## Fırsat puanı (Aşama 7)

Tüm semboller her saat (ayarlanabilir) 14 stratejiyle değerlendirilir ve 0-100 arası
**açıklanabilir** bir puan alır.
- **Bileşenler:** strateji uzlaşısı, trend, momentum, hacim/akış, balina, emir defteri,
  tarihsel benzerlik, model.
- **Cezalar:** işlem maliyeti (komisyon + spread + kayma + funding), ödül/risk, likidite.

Her puanın yanında aynı puan aralığının geçmişteki maliyet sonrası sonucu gösterilir. **Puan
emir vermez.**

```bash
# Geçmiş veride kalibrasyon (sonuç motorun veri dizinine kaydedilir, canlı puanlara eklenir)
uv run ati-engine score-calibrate --symbol BTCUSDT ETHUSDT
uv run ati-engine score-calibrate --market usdm_futures --symbol BTCUSDT ETHUSDT
```

```toml
[scoring]
interval = "1h"          # 15m | 30m | 1h | 2h | 4h
horizon_bars = 4
publish_min_score = 60
spot_taker_fee = 0.001   # BNB indirimi vb. varsa düşürün
futures_taker_fee = 0.0005
# models = { spot = { long = "<model kimliği>", short = "<model kimliği>" } }
```

Yerel API:
- `GET /v1/opportunities?market=spot&min_score=60`
- `GET /v1/opportunities/detail?symbol=BTCUSDT`: tam döküm.
- `GET /v1/opportunities/strategies`
- `GET /v1/opportunities/calibration`
- `GET /v1/opportunities/stats`

## Analiz motoru ve model (Aşama 6)

- **Göstergeler:** RSI, MACD, EMA 9/21/50/200, Bollinger, ATR, OBV, Stochastic RSI,
  Ichimoku, VWAP, Fibonacci. Artımlı hesaplanır ve TA-Lib ile birebir doğrulanmıştır.
- **Özellikler:** aynı kodla hem eğitimde hem canlıda üretilir.
- **Model:** LightGBM; yürüyen pencereyle (zaman sızıntısı olmadan) eğitilir, ONNX olarak
  saklanır.

```bash
uv run ati-engine model-train --symbol BTCUSDT ETHUSDT --interval 1h --horizon 4 --side long
uv run ati-engine model-train --market usdm_futures --symbol BTCUSDT --with-futures --since 2022-01-01
```

Yerel API:
- `GET /v1/analysis/snapshot?symbol=BTCUSDT&interval=1h`: göstergeler ve özellikler.
- `POST /v1/analysis/train`, `GET /v1/analysis/jobs`
- `GET /v1/analysis/models`: örneklem dışı metrikler ve kalibrasyon.
- `GET /v1/analysis/predict?model_id=...&symbol=BTCUSDT`

Rapordaki metrikler geçmiş veride ölçülür. Gerçek veride eğitilen modeller rastgeleden iyi
ama **işlem maliyeti sonrası kârlı değil** (ayrıntı: `docs/05-gelistirme-plani.md`, Aşama 6).
Model çıktısı tek başına işlem kararı değildir.

## Coin tarama (Aşama 3)

İzlenen tüm semboller için saniyede bir yenilenen tablo (1/5/15 dk ve 24 saat değişim, hacim
ve fiyat z-skorları, agresif alış/satış dengesizliği, odak sembollerinde spread ve derinlik)
ve sinyaller (hacim patlaması, ani hareket, alıcı/satıcı baskısı, derinlik düşüşü, yeni
listeleme). Yerel API: `GET /v1/scanner/top?market=spot&sort=volume_z_60s&limit=50`,
`GET /v1/scanner/signals?limit=100`.

## Balina radarı (Aşama 4)

Yalnızca **herkese açık** Binance piyasa verisi kullanılır; hiçbir kişinin hesabına erişilmez.

- **Büyük işlemler:** aynı milisaniyedeki parçalı dolumlar tek emir olarak birleştirilir;
  eşik her sembol için ayrı öğrenilir (son işlemlerin %99,9'luk dilimi, en az 50 bin $ Spot /
  100 bin $ Futures).
- **Kümelenme:** 5 dakika içinde aynı yönde en az 3 büyük emir → birikim/dağıtım uyarısı;
  Spot ve Futures aynı yöndeyse "iki piyasada teyitli" olarak işaretlenir.
- **Emir defteri duvarları** (odak sembolleri): ortanca seviyenin 8 katı ve en az 250 bin $
  (Futures 500 bin $) duvarlar; çekilme ve yenilme ayrı ayrı bildirilir, 5 sn'den kısa
  ömürlü duvarlar yok sayılır.
- **Tasfiyeler:** büyük tasfiyeler ve 60 sn içindeki tasfiye zincirleri. Binance saniyede
  yalnızca en büyük tasfiyeyi yayınladığı için toplamlar **alt sınırdır**.
- **Büyük oyuncu konumlanması:** en yüksek hacimli Futures sembolleri için büyük oyuncu ve
  genel long/short oranları ile açık pozisyon (5 dakikada bir); büyükler ile kalabalık ters
  yöne giderse ayrışma uyarısı.
- **Fiyat etkisi:** her balina uyarısından 1, 5, 15 ve 60 dakika sonra fiyat değişimi ölçülür
  ve yöne göre (alış için yükseliş olumlu) istatistik tutulur. Bu istatistik geçmişi anlatır,
  gelecekteki fiyatı garanti etmez.
- **Zincir üstü (varsayılan kapalı):** sağlayıcıdan bağımsız arayüz ve kullanıcının verdiği
  adres etiketleriyle borsa giriş/çıkış sınıflandırması. Ticari kullanıma izin veren bir veri
  sağlayıcısının seçimi onay kapısı **G4**'e bağlıdır.

```toml
[whales]
spot_floor_usd = 50000
futures_floor_usd = 100000
alert_cooldown_s = 300

[whales.onchain]
enabled = false          # G4 onayı ve sağlayıcı anahtarı olmadan açmayın
labels_file = "labels.json"   # {"ethereum": {"0x...": "Binance"}}
```

Yerel API: `GET /v1/whales/trades?market=spot&symbol=BTCUSDT`, `GET /v1/whales/alerts`,
`GET /v1/whales/summary?market=usdm_futures`, `GET /v1/whales/impact`,
`GET /v1/whales/positioning`. Uyarılar masaüstüne olay olarak iletilir ve `whale_alerts`,
etki ölçümleri `whale_impacts` tablosuna yazılır.

Motor her zaman **PAPER (sanal işlem)** modunda başlar. Gerçek emir yürütme modülü
Aşama 10'a kadar bulunmadığından LIVE moduna geçiş teknik olarak engellenmiştir.

Yerel API yalnızca `127.0.0.1` üzerinde açılır. Belirteç, masaüstü uygulaması tarafından
`ATI_LOCAL_API_TOKEN` ortam değişkeniyle verilir; verilmezse motor rastgele bir belirteç
üretip `runtime/local-api.json` dosyasına (yalnızca kullanıcı okuyabilir) yazar.
