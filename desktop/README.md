# desktop — Windows Masaüstü Uygulaması (Aşama 12)

Henüz geliştirilmedi. Plan: Tauri 2 (Rust kabuk) + React + TypeScript +
TradingView Lightweight Charts.

* Kabuk, `ati-engine` motorunu sidecar olarak başlatır; rastgele belirteci
  `ATI_LOCAL_API_TOKEN` ortam değişkeniyle iletir ve motoru gözetler.
* Motorla sözleşme: [`../shared/protocol/engine-local-api.schema.json`](../shared/protocol/engine-local-api.schema.json).
  TypeScript tipleri bu şemadan üretilecek.
* Kapanışta `POST /v1/engine/shutdown` ile düzgün kapatma.

Ayrıntılar: [`../docs/01-sistem-mimarisi.md`](../docs/01-sistem-mimarisi.md) §3.3,
[`../docs/05-gelistirme-plani.md`](../docs/05-gelistirme-plani.md) Aşama 12.
