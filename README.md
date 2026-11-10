# AI Trading Intelligence

Binance Spot ve USDⓈ-M Futures piyasalarını gerçek zamanlı izleyen, çok stratejili yapay
zekâ analizi yapan ve sıkı risk kontrolleri altında işlem yapabilen ticari bir algoritmik
işlem platformu.

> ⚠️ **Risk bildirimi:** Kripto para işlemleri yüksek risk taşır ve yatırdığınız paranın
> tamamını kaybedebilirsiniz. Bu yazılım hiçbir kazanç garantisi vermez. Geçmiş performans
> gelecekteki sonuçların göstergesi değildir.

## Bileşenler

| Bileşen | Klasör | Teknoloji | Durum |
|---|---|---|---|
| İşlem motoru (kullanıcının Windows bilgisayarında) | [`engine/`](engine/) | Python 3.12+, asyncio | ✅ Çekirdek, Binance veri motoru, coin tarayıcı, balina radarı, tarihsel veri, grafik analizi, göstergeler, model, 14 strateji, fırsat puanı, backtest, sanal işlem yarışması, test ağı emir yürütme, risk kapısı ve risk bekçisi, test ağında otomatik işlem; gerçek hesap G1/G2 onayına kadar kilitli (Aşama 1-11); lisans kirası ve işlem kapısı (Aşama 15); yedekleme/geri yükleme ve dayanıklılık testi (Aşama 18) |
| Bulut servisi: lisans, hesap, ödeme, aktarma | [`cloud/`](cloud/) | FastAPI, PostgreSQL 16 | ✅ Şema + iskelet (Aşama 1), aktarma servisi (Aşama 13), müşteri hesapları ve iletişim API'si (Aşama 14), lisans sistemi (Aşama 15), yönetici API'si (Aşama 16), ödeme ve lisans teslimi: PayTR, iyzico, test simülatörü (Aşama 17), istek koruması, yük testi ve felaket kurtarma tatbikatı (Aşama 18); dağıtım G5, canlı ödeme G3 onayı bekliyor |
| Paylaşılan protokol | [`shared/protocol/`](shared/protocol/) | JSON Schema | ✅ |
| Windows masaüstü uygulaması | [`desktop/`](desktop/) | Tauri 2, React, TypeScript | ✅ 10 ekran, motor gözetmeni, NSIS kurulum paketi (imzasız; kod imzalama G6 onayı bekliyor) (Aşama 12) |
| iOS uygulaması | [`ios/`](ios/) | Swift, SwiftUI | ✅ Eşleştirme, özet, acil durdurma, bot, pozisyonlar (Face ID), sinyaller, bildirimler; uçtan uca imzalı komutlar (Aşama 13), uçtan uca şifreli mesajlar (Aşama 18). Cihaza kurulum Apple hesabı (G6) bekliyor |
| Web sitesi ve paneller | [`web/`](web/) | Next.js, TypeScript, Tailwind | ✅ Tanıtım sayfaları, paketler, hesap (kayıt/giriş/parola sıfırlama), müşteri paneli, SSS, iletişim, yasal taslaklar; axe 0 ihlal, Lighthouse 97-100 (Aşama 14). Yönetim paneli: paketler/fiyatlar, lisanslar, müşteriler, ödeme ayarları, yöneticiler; TOTP zorunlu (Aşama 16). Satın alma, sonuç sayfası, siparişler, iade, mesafeli satış/ön bilgilendirme taslakları (Aşama 17). İndirme sayfası (`/indir`) ve panelden sürüm yayınlama; üretim imajları (`web/Dockerfile`, `cloud/Dockerfile`). Alan adı: canarslan.net.tr ([`deploy/`](deploy/)) |

**Durum:** 18 aşamanın tamamı kod ve testleriyle bitti. Yayın; onay kapılarına (G1–G6) ve
sizden beklenen bilgilere bağlıdır: ödeme sağlayıcısı test hesabı, şirket bilgileri, hukukçu
onayı, bulut sağlayıcısı (`docs/05`). Güvenlik taraması, sızma testi tarzı testler, yük testi,
dayanıklılık testi ve felaket kurtarma tatbikatı CI'da çalışır (aşağıda "Otomatik testler").

## Belgeler

1. [Sistem mimarisi](docs/01-sistem-mimarisi.md)
2. [Teknoloji seçimleri ve gerekçeleri](docs/02-teknoloji-secimleri.md)
3. [Klasör yapısı](docs/03-klasor-yapisi.md)
4. [Veritabanı şeması](docs/04-veritabani-semasi.md)
5. [Teknik geliştirme planı (18 aşama, onay kapıları)](docs/05-gelistirme-plani.md)
6. [Güvenlik tasarımı](docs/06-guvenlik.md)

## Güvenlik ilkeleri (özet)

* Motor **her zaman sanal işlem (PAPER) modunda başlar.** Gerçek işlem; ayar dosyasında
  bilinçli olarak açılmayı, çalışma anında açık onay ifadesini ve tüm ön koşulları ister.
  Bu sürümde gerçek emir yürütücüsü yoktur; LIVE modu teknik olarak engellidir.
* Binance API anahtarları kullanıcının bilgisayarından **hiç çıkmaz**, Windows DPAPI ile
  şifrelenir. Para çekme yetkisi açık anahtarlar reddedilir.
* Acil durdurma kalıcıdır, her yerden devreye alınabilir, yalnızca açık onayla kaldırılır.
* Piyasa verisi koptuğunda veya gecikirse motor otomatik olarak güvenli moda geçer; bu modda
  yeni pozisyon açılmaz.
* Kritik işlemler hash zincirli, değiştirilemez denetim kaydına yazılır.

## Hızlı başlangıç (geliştirici)

Gereksinimler: [uv](https://docs.astral.sh/uv/), Python 3.12+, bulut testleri için PostgreSQL 16.

```bash
# Motor
cd engine
uv sync
uv run pytest
uv run ati-engine run --data-dir ./.data --port 0     # PAPER modunda başlar

# Bulut
cd ../cloud
uv sync
ATI_TEST_DATABASE_URL=postgresql://ati_test:ati_test@127.0.0.1:5432/ati_test uv run pytest
```

Motor çalışırken (`runtime/local-api.json` dosyasındaki port ve belirteçle):

```bash
curl http://127.0.0.1:<port>/v1/health
curl -H "Authorization: Bearer <belirteç>" http://127.0.0.1:<port>/v1/status
curl -X POST -H "Authorization: Bearer <belirteç>" -H "Content-Type: application/json" \
     -d '{"reason":"test"}' http://127.0.0.1:<port>/v1/kill-switch/engage
```

## Otomatik testler (GitHub Actions)

Depo özel olduğu için GitHub Actions aylık **2.000 ücretsiz dakikayla** sınırlıdır. Windows
makinesinde geçen 1 dakika kotadan 2, macOS makinesinde geçen 1 dakika 10 dakika düşer. Kota bitince
işler hiç başlamadan (~2 sn) başarısız olur ve bir sonraki ay yenilenir (Settings → Billing and
licensing → Usage). Kotayı korumak için:

| İş akışı | Kendiliğinden (gönderimde) | Elle (**Actions → iş akışı → Run workflow**) |
|---|---|---|
| CI | Motor/bulut değişince: motor (Linux, Py 3.13), bulut, lisans uçtan uca, üretim bağımlılıklarıyla açılış | + Py 3.12, Linux dayanıklılık testi |
| Windows (motor) | Motor değişince: Windows testleri + 3 dk dayanıklılık | Aynısı |
| Masaüstü | Masaüstü/motor değişince: arayüz ve Rust kabuğu (Linux) | + **Windows kurulum paketi** (indirme dosyası) |
| iOS | iOS değişince: çekirdek testleri (Linux) | + macOS uygulama ve arayüz testleri |
| Web sitesi | Web/bulut değişince: birim, uçtan uca, axe, Lighthouse | + Docker üretim imajları |
| Güvenlik taraması | Her gönderimde ve haftalık | Aynısı |

`ana` dalı yalnızca testleri geçmiş işlemeye ileri sarılır; aynı işleme orada yeniden test
edilmez.

## Lisans

Tescilli yazılım. Tüm hakları saklıdır.
