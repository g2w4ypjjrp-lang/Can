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
