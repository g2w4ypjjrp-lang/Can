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
| İşlem motoru (kullanıcının Windows bilgisayarında) | [`engine/`](engine/) | Python 3.12+, asyncio | ✅ Çekirdek, Binance veri motoru, coin tarayıcı, balina radarı, tarihsel veri, grafik analizi, göstergeler, model, 14 strateji, fırsat puanı, backtest, sanal işlem yarışması, test ağı emir yürütme, risk kapısı ve risk bekçisi, test ağında otomatik işlem; gerçek hesap G1/G2 onayına kadar kilitli (Aşama 1-11) |
| Bulut servisi: lisans, hesap, ödeme, aktarma | [`cloud/`](cloud/) | FastAPI, PostgreSQL 16 | ✅ Şema + iskelet (Aşama 1), aktarma servisi (Aşama 13), müşteri hesapları ve iletişim API'si (Aşama 14); dağıtım G5 onayı bekliyor |
| Paylaşılan protokol | [`shared/protocol/`](shared/protocol/) | JSON Schema | ✅ |
| Windows masaüstü uygulaması | [`desktop/`](desktop/) | Tauri 2, React, TypeScript | ✅ 10 ekran, motor gözetmeni, NSIS kurulum paketi (imzasız; kod imzalama G6 onayı bekliyor) (Aşama 12) |
| iOS uygulaması | [`ios/`](ios/) | Swift, SwiftUI | ✅ Eşleştirme, özet, acil durdurma, bot, pozisyonlar (Face ID), sinyaller, bildirimler; uçtan uca imzalı komutlar (Aşama 13). Cihaza kurulum Apple hesabı (G6) bekliyor |
| Web sitesi ve paneller | [`web/`](web/) | Next.js, TypeScript, Tailwind | ✅ Tanıtım sayfaları, paketler, hesap (kayıt/giriş/parola sıfırlama), müşteri paneli, SSS, iletişim, yasal taslaklar; axe 0 ihlal, Lighthouse 96-100 (Aşama 14). Admin paneli Aşama 16 |

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

## Lisans

Tescilli yazılım. Tüm hakları saklıdır.
