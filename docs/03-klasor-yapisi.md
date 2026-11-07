# 03 — Klasör Yapısı

Tek depo (monorepo). Her uygulama kendi bağımlılık ve kilit dosyasına sahiptir; böylece
masaüstü motoru paketi bulut bağımlılıklarını taşımaz.

✅ = bu aşamada mevcut ve test edilmiş · 🔜 = planlanan (aşama numarasıyla)

```text
.
├── README.md                          ✅ Proje özeti, hızlı başlangıç, belge dizini
├── .github/workflows/ci.yml           ✅ CI: motor (Windows + Linux, Py 3.12/3.13), bulut (PostgreSQL 16)
├── docs/                              ✅ Mimari, teknoloji, şema, plan, güvenlik
│
├── engine/                            ✅ İşlem motoru (Python) — Windows'ta çalışır
│   ├── pyproject.toml, uv.lock
│   ├── src/ati_engine/
│   │   ├── __main__.py                ✅ CLI: run, show-config, verify-audit, export-protocol-schema
│   │   ├── app.py                     ✅ Bileşim kökü ve yaşam döngüsü
│   │   ├── config.py                  ✅ Ayarlar (env + config.toml), güvenli varsayılanlar, sert üst sınırlar
│   │   ├── runtime.py                 ✅ Çalışan bileşenlere erişim
│   │   ├── protocol.py                ✅ Paylaşılan protokol şeması üretimi
│   │   ├── core/                      ✅ models, events, bus, supervisor, clock
│   │   ├── safety/                    ✅ state, coordinator, kill_switch, trading_mode
│   │   ├── security/                  ✅ vault (DPAPI/AES-GCM), binance_key_policy, redaction
│   │   ├── storage/                   ✅ database (SQLite+geçiş), audit, settings_store, migrations/*.sql
│   │   ├── observability/             ✅ logging (JSON + maskeleme), loop_monitor
│   │   ├── system/                    ✅ paths, single_instance
│   │   ├── api/                       ✅ server (REST + WS), schemas
│   │   ├── exchange/                  ✅ 2  REST istemcisi, HMAC/Ed25519 imzalama, ağırlık bütçesi, uç noktalar
│   │   ├── market/                    ✅ 2  keşif, WebSocket akışları, emir defteri, boşluk doldurma, servis
│   │   ├── scanner/                   ✅ 3  coin tarama: artımlı istatistikler, sinyal kuralları, ısınma
│   │   ├── whales/                    ✅ 4  balina radarı: büyük işlem, küme, duvar, tasfiye,
│   │   │                                    konumlanma, fiyat etkisi, zincir üstü arayüzü
│   │   ├── history/                   🔄 5  arşiv indirme + CHECKSUM ✅, DuckDB deposu ✅, artımlı
│   │   │                                    eşitleme ✅; teknik analiz araçları sırada
│   │   ├── analysis/                  🔜 6  göstergeler (artımlı), özellikler, modeller
│   │   ├── strategies/                🔜 6,9 10+ strateji, yarışma ve ağırlıklandırma
│   │   ├── scoring/                   🔜 7  fırsat puanı 0-100
│   │   ├── backtest/                  🔜 8  olay güdümlü geriye dönük test, walk-forward
│   │   ├── execution/                 🔜 9-10 paper/testnet/live yürütücüler, emir yöneticisi
│   │   ├── risk/                      🔜 11 risk kapısı ve bağımsız risk bekçisi
│   │   ├── licensing/                 🔜 15 lisans kirası doğrulama
│   │   └── remote/                    🔜 13 aktarma istemcisi, imzalı komut doğrulama
│   ├── scripts/live_soak.py           ✅ Gerçek Binance verisiyle dayanıklılık testi (veri kaybı ölçümü)
│   └── tests/                         ✅ 252 test (birim, gerçek mesaj fikstürleri, sahte Binance
│                                          sunucusuyla uçtan uca, alt süreç duman testi)
│
├── cloud/                             ✅ Bulut servisi (FastAPI) — yönetilen bulutta çalışır
│   ├── pyproject.toml, uv.lock
│   ├── src/ati_cloud/
│   │   ├── app.py                     ✅ /health, /ready
│   │   ├── config.py                  ✅ Üretimde sertifika doğrulamalı TLS zorunlu
│   │   ├── db/migrate.py              ✅ Geçiş çalıştırıcısı (özet + advisory lock)
│   │   ├── db/migrations/0001_*.sql   ✅ Tam şema (lisans, cihaz, ödeme, admin, denetim)
│   │   ├── db/migrations/0002_*.sql   ✅ Roller/yetkiler ve 16 lisans paketi
│   │   ├── auth/                      🔜 15 müşteri kimlik doğrulama
│   │   ├── licensing/                 🔜 15 anahtar üretimi, tahsis, aktivasyon, kira imzalama
│   │   ├── admin/                     🔜 16 ayrı yönetici API'si (2FA + RBAC)
│   │   ├── payments/                  🔜 17 sağlayıcı soyutlaması, webhook, teslim
│   │   └── relay/                     🔜 13 iOS ↔ motor aktarma servisi
│   └── tests/                         ✅ 53 test (gerçek PostgreSQL üzerinde)
│
├── shared/protocol/                   ✅ engine-local-api.schema.json (CI ile koddan senkron)
├── desktop/                           🔜 12 Tauri 2 + React + Lightweight Charts
├── ios/                               🔜 13 SwiftUI uygulaması
└── web/                               🔜 14 Next.js web sitesi, müşteri paneli, admin paneli
```

## Kullanıcı bilgisayarındaki veri dizini

`%LOCALAPPDATA%\AITradingIntelligence\` (yalnızca o Windows kullanıcısı erişebilir):

```text
config.toml          kullanıcı ayarları (gizli bilgi yok)
engine.db            SQLite: emirler, pozisyonlar, karar günlüğü, şifreli gizli bilgiler, denetim kaydı
engine.lock          tek örnek kilidi
market/history.duckdb  tarihsel mumlar (DuckDB, Aşama 5)
models/              yapay zekâ modelleri (Aşama 6)
logs/engine.jsonl    dönen JSON loglar (maskelenmiş)
runtime/             yerel API port bilgisi (motor çalışırken)
```
