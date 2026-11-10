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
karar günlüğü, risk olayları), Strateji performansı, Telefon (QR ile iPhone eşleştirme, telefondan
kontrol), Ayarlar (işlem modu, test ağı anahtarı, lisans, denetim kaydı).

Tasarım: koyu tema, web sitesiyle aynı marka renkleri (mavi → mor degrade), gruplu ve ikonlu menü
(Genel / İşlem / Sistem), üst çubukta motor, işlem modu ve telefon durumu.

## Lisans

Kurulum paketinde lisans **zorunludur**: geçerli lisans yoksa uygulama yerine yalnızca "Lisansınızı
etkinleştirin" ekranı açılır; motor da lisanssız yeni işlem açmaz. Acil durdurma bu ekranda da
kullanılabilir; açık pozisyonların borsadaki stopları korunur. Lisans anahtarı müşteri panelinde
(canarslan.net.tr/panel) görünür; yönetici, panelde **Lisanslar → Lisans üret** ile bir müşteri
hesabına anahtar üretebilir. Kaynaktan çalıştırmada (geliştirme, testler) lisans zorunlu değildir.

## Binance Demo Trading anahtarı

Binance, test ağını Demo Trading'e taşıdı. Anahtar **demo.binance.com → API Management → Create API**
ile oluşturulur (sahte bakiye, gerçek fiyatlar). Gerçek hesap anahtarı ve eski testnet.binance.vision
anahtarı çalışmaz. Eski test ağı adresleri gerekirse `ATI_BINANCE__FUTURES_TESTNET_REST` vb. ile
verilebilir.

## Telefondan kontrol

1. **Telefon** ekranında "Telefondan kontrol" anahtarını açın. Varsayılan kapalıdır; açılmadan motor
   hiçbir dış servise bağlanmaz. Seçim saklanır, yeniden başlatmada geçerlidir.
2. Motor şifreli aktarma servisine (`wss://relay.canarslan.net.tr`) bağlanır. **QR kodu göster** →
   iPhone uygulamasında "Bilgisayarı eşleştir" ile okutun. Kod 5 dakika geçerli, tek kullanımlıktır;
   eşleşme ekranda kendiliğinden görünür.
3. Telefondan yapılabilenler: durum ve pozisyonları görme, acil durdurma, botu durdurma; Face ID ile
   botu başlatma, pozisyon kapatma, acil durdurmayı kaldırma. Yeni işlem açma, ayar değiştirme ve para
   çekme telefondan yapılamaz.

Kapatınca bağlantı kesilir ve bekleyen kod geçersizleşir; eşli telefonlar silinmez ("Eşleştirmeyi
kaldır" ile tek tek kaldırılır). Kendi aktarma servisi için motor ayarı: `ATI_REMOTE__RELAY_URL`.

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
