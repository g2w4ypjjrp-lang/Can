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
│   │   ├── security/                  ✅ vault (DPAPI/AES-GCM), binance_key_policy, redaction,
│   │   │                                    exchange_keys (10: yalnızca test ağı anahtarı)
│   │   ├── storage/                   ✅ database (SQLite+geçiş), audit, settings_store, migrations/*.sql
│   │   ├── observability/             ✅ logging (JSON + maskeleme), loop_monitor
│   │   ├── system/                    ✅ paths, single_instance
│   │   ├── api/                       ✅ server (REST + WS), schemas
│   │   ├── exchange/                  ✅ 2  REST istemcisi, HMAC/Ed25519 imzalama, ağırlık bütçesi, uç noktalar
│   │   ├── market/                    ✅ 2  keşif, WebSocket akışları, emir defteri, boşluk doldurma, servis
│   │   ├── scanner/                   ✅ 3  coin tarama: artımlı istatistikler, sinyal kuralları, ısınma
│   │   ├── whales/                    ✅ 4  balina radarı: büyük işlem, küme, duvar, tasfiye,
│   │   │                                    konumlanma, fiyat etkisi, zincir üstü arayüzü
│   │   ├── history/                   ✅ 5  arşiv + CHECKSUM, DuckDB, artımlı eşitleme + REST
│   │   │                                    onarımı, destek/direnç, trend kırılımı, benzerlik,
│   │   │                                    balina yeniden oynatma
│   │   ├── analysis/                  ✅ 6  artımlı göstergeler (TA-Lib ile doğrulanmış), özellikler
│   │   ├── ml/                        ✅ 6  veri kümesi, yürüyen pencere LightGBM, ONNX kayıt defteri
│   │   ├── strategies/                ✅ 7  14 strateji + sembol defteri
│   │   ├── scoring/                   ✅ 7  maliyet modeli, açıklanabilir 0-100 puan, kalibrasyon,
│   │   │                                    canlı fırsat motoru
│   │   ├── backtest/                  ✅ 8  olay güdümlü motor, metrikler, yürüyen pencere, arındırılmış CV,
│   │   │                                    strateji kayıt defteri ve terfi
│   │   ├── execution/                 ✅ 9  emir defteri tabanlı sanal dolum
│   │   │                              ✅ 10 emir yöneticisi (idempotent), pozisyon defteri, işlem
│   │   │                                    motoru (stop/hedef/başa baş/OCO), Binance yürütücüleri,
│   │   │                                    mutabakat, test ağı servisi (gerçek hesap: G1/G2)
│   │   │                              ✅ 11 otomatik işlem (test ağı, varsayılan kapalı)
│   │   ├── paper/                     ✅ 9  sanal işlem yarışması: bağımsız hesaplar, terfi hattı
│   │   ├── risk/                      ✅ 11 risk kapısı (imzalı tek kullanımlık onay), hesap izleyici,
│   │   │                                    bağımsız risk bekçisi
│   │   ├── licensing/                 ✅ 15 cihaz kimliği, kira doğrulama, yenileme, işlem kapısı
│   │   └── remote/                    ✅ 13 eşleştirme, imzalı komut doğrulama, aktarma istemcisi
│   ├── scripts/live_soak.py           ✅ Gerçek Binance verisiyle dayanıklılık testi (veri kaybı ölçümü)
│   ├── packaging/                     ✅ 12 PyInstaller tanımı (tek klasör motor paketi)
│   └── tests/                         ✅ 473 test (birim, gerçek mesaj fikstürleri, sahte Binance
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
│   │   ├── licensing/                 ✅ 15 anahtar üretimi, saklama, aktivasyon, kira imzalama, CLI
│   │   ├── admin/                     ✅ 16 yönetici API'si: davet + TOTP, rol bazlı yetki, paket/lisans/müşteri/ayar yönetimi, CLI
│   │   ├── payments/                  🔜 17 sağlayıcı soyutlaması, webhook, teslim
│   │   └── relay/                     🔜 13 iOS ↔ motor aktarma servisi
│   └── tests/                         ✅ 53 test (gerçek PostgreSQL üzerinde)
│
├── shared/protocol/                   ✅ engine-local-api.schema.json (CI ile koddan senkron),
│                                            remote-v1.md + test-vectors (uzaktan kontrol protokolü)
├── deploy/                            ✅ Üretim yapısı (canarslan.net.tr) ve gizli bilgi içermeyen ayar örnekleri
├── desktop/                           ✅ 12 Windows uygulaması
│   ├── src/                           ✅ React + TypeScript: 10 ekran, API istemcisi, olay akışı,
│   │                                        şemadan üretilen tipler (api/types.gen.ts)
│   ├── src-tauri/                     ✅ Rust kabuk: motor gözetmeni (belirteç, sağlık, yeniden
│   │                                        başlatma, düzgün kapatma, iş nesnesi), NSIS paketi
│   ├── e2e/                           ✅ Playwright uçtan uca testleri (8 senaryo)
│   └── scripts/gen-types.mjs          ✅ protokol şemasından TypeScript tipleri
├── ios/                               ✅ 13 iOS uygulaması
│   ├── ATICore/                       ✅ Swift paketi: protokol, imza, doğrulama, oturum denetleyicisi,
│   │                                        motor benzetimi (Linux ve macOS'ta test edilir)
│   ├── App/                           ✅ SwiftUI ekranları, Secure Enclave anahtarları, WebSocket
│   ├── AppUITests/                    ✅ XCUITest senaryoları
│   └── project.yml                    ✅ XcodeGen proje tanımı
└── web/                               ✅ 14 Next.js web sitesi, müşteri paneli; 16 yönetim paneli
    ├── app/(site)/                    ✅ herkese açık sayfalar: tanıtım, paketler, hesap, panel, yasal
    ├── app/yonetim/                   ✅ 16 yönetim paneli (admin. alan adı, TOTP, rol bazlı menü)
    ├── components/                    ✅ arayüz bileşenleri, hesap formları
    ├── lib/                           ✅ API istemcisi, CSP, biçimlendirme, içerik kuralı
    ├── proxy.ts                       ✅ istek başına nonce'lu CSP ve HSTS
    ├── tests/                         ✅ birim testleri (vitest)
    ├── e2e/                           ✅ Playwright + axe (gerçek API + PostgreSQL)
    └── lighthouserc.cjs               ✅ Lighthouse CI eşikleri
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
