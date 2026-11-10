# desktop — Windows Masaüstü Uygulaması (Aşama 12)

Tauri 2 (Rust kabuk) + React + TypeScript + TradingView Lightweight Charts.

## Mimari

- **Kabuk (`src-tauri/`)** işlem motorunu başlatır ve gözetir:
  - Motor kurulumla gelen `engine/ati-engine.exe` klasöründen başlar.
  - Her açılışta rastgele 256 bit oturum belirteci üretilir ve motora `ATI_LOCAL_API_TOKEN`
    ortam değişkeniyle verilir; belirteç diske yazılmaz. Motor yalnızca 127.0.0.1'i dinler.
  - Motor çökerse artan beklemeyle yeniden başlatılır (10 dakikada en fazla 5 kez).
  - Pencere kapanınca motora düzgün kapanma isteği gider; en fazla 20 sn beklenir.
  - Windows iş nesnesi: kabuk zorla kapatılsa da motor açık kalmaz.
  - Tek örnek: uygulama ikinci kez açılırsa mevcut pencere öne gelir.
- **Arayüz (`src/`)** motorun yerel API'sini (`/v1/*`) ve olay akışını (`/v1/events`) kullanır.
  Tipler paylaşılan şemadan üretilir: `npm run gen:types`
  ([`../shared/protocol/engine-local-api.schema.json`](../shared/protocol/engine-local-api.schema.json)).
  CSP yalnızca 127.0.0.1'e bağlantıya izin verir.

## Ekranlar

Genel bakış (motor durumu, acil durdurma, bot başlat/durdur, hazırlık koşulları), Piyasa (tüm
coinler, anormal hareketler), Fırsatlar (açıklanabilir puan ve gerekçeler), Balina radarı,
Grafik ve AI analiz (mum grafiği, destek/direnç, trend, model tahmini), Spot/Futures işlemler
(test ağı pozisyonları, emirler, yeni işlem formu, kapatma), Kâr/zarar ve geçmiş, Risk (sınırlar,
karar günlüğü, risk olayları), Strateji performansı, Ayarlar (işlem modu, test ağı anahtarı,
denetim kaydı).

## Geliştirme

```bash
npm ci
npm run dev                    # tarayıcıda: http://127.0.0.1:1420/#engine=http://127.0.0.1:47821&token=...
npm test                       # birim testleri (vitest)
npm run build && npm run e2e   # uçtan uca: gerçek motor + sahte Binance (engine/tests/e2e_backend.py)
```

Masaüstü kabuğuyla geliştirme (motor `uv` ile):

```bash
ATI_ENGINE_EXE=uv ATI_ENGINE_ARGS="run --project ../engine ati-engine" npx tauri dev
```

## Kurulum paketi

Kurulum paketi GitHub Actions'ta **elle** derlenir (Windows dakikası ücretsiz kotadan 2 kat
düşer): **Actions → Masaüstü → Run workflow**. Windows işi (`.github/workflows/desktop.yml`) şu
adımları izler:

1. Motoru PyInstaller ile paketler (`engine/packaging/ati-engine.spec`, tek klasör).
2. NSIS kurulum paketini derler. Kullanıcı başına kurulur, yönetici yetkisi istemez.
3. Temiz Windows makinesinde test eder: sessiz kurulum → uygulama açılır ve motoru başlatır →
   kabuk zorla kapatılınca motor da kapanır → sessiz kaldırma.

Kurulum paketi **imzasızdır**. Kod imzalama sertifikası onayınızı (**G6**) bekler; imzasız
pakette Windows SmartScreen uyarı gösterebilir.

**Otomatik güncelleme** henüz yok. Güncelleme sunucusu (**G5**) ve güncelleme imza anahtarıyla
birlikte etkinleşecek.
