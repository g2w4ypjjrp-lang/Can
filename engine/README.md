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

Motor her zaman **PAPER (sanal işlem)** modunda başlar. Bu sürümde (Aşama 2) gerçek emir
yürütme modülü bulunmadığından LIVE moduna geçiş teknik olarak engellenmiştir.

Yerel API yalnızca `127.0.0.1` üzerinde açılır. Belirteç, masaüstü uygulaması tarafından
`ATI_LOCAL_API_TOKEN` ortam değişkeniyle verilir; verilmezse motor rastgele bir belirteç
üretip `runtime/local-api.json` dosyasına (yalnızca kullanıcı okuyabilir) yazar.
