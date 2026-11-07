# 02 — Teknoloji Seçimleri ve Gerekçeleri

Her seçim için: neden seçildi, hangi alternatifler değerlendirildi ve neden elendi.
Kararlar geri alınabilir; arayüzler (yerel API şeması, SQL şemaları) teknolojiden bağımsız
tutuldu.

## Özet tablo

| Katman | Seçim | Kısa gerekçe |
|---|---|---|
| İşlem motoru | **Python 3.12+ / asyncio**, `msgspec`, `numpy`/`polars`; sıcak yollar gerekirse **Rust (PyO3)** | Yapay zekâ/veri bilimi ekosistemi; ölçüm gerektirirse Rust'a kademeli geçiş |
| Yapay zekâ | Eğitim: **PyTorch** + **LightGBM**; Çıkarım: **ONNX Runtime** | Tablo verisinde ağaç modelleri güçlü; ONNX ile küçük ve hızlı dağıtım |
| Masaüstü (Windows EXE) | **Tauri 2** (Rust kabuk) + **React + TypeScript** + **TradingView Lightweight Charts** | Profesyonel grafik, web ile ortak bileşen, küçük kurulum boyutu |
| iOS | **Swift / SwiftUI**, Swift Concurrency, Keychain + Secure Enclave, APNs, Swift Charts | Yerel performans ve donanım tabanlı anahtar güvenliği |
| Web | **Next.js (App Router) + TypeScript**, Tailwind | SEO, sunucu tarafı oluşturma, ekip verimliliği |
| Bulut API | **Python FastAPI**, `psycopg 3`, SQL-öncelikli geçişler | Motorla aynı dil ve modeller; şeffaf, gözden geçirilebilir SQL |
| Merkezi veritabanı | **Yönetilen PostgreSQL 16** | İşlemsel bütünlük, kısıtlar, tetikleyiciler, olgun ekosistem |
| Önbellek / hız sınırlama / aktarma | **Yönetilen Redis** | Hız sınırlama, kısa ömürlü belirteçler, örnekler arası pub/sub |
| Yerel işlemsel veri | **SQLite (WAL, STRICT)** | Sunucusuz, tek dosya, çökmeye dayanıklı |
| Yerel tarihsel veri | **Parquet + DuckDB** | Gömülü, sütun tabanlı, sıkıştırılmış, hızlı analitik |
| Gerçek zamanlı iletişim | **WebSocket** (Binance, yerel API, aktarma) | Tüm uçlarda standart, düşük gecikme |
| Barındırma | **Yönetilen kapsayıcı platformu** (Cloud Run / App Runner / Fly.io vb.) | VDS yönetimi yok, otomatik ölçekleme, yamalar sağlayıcıda |
| Paket yönetimi | `uv` (Python), `pnpm` (JS), kilit dosyaları | Tekrarlanabilir kurulum, tedarik zinciri güvenliği |

## Veritabanı değerlendirmesi (istenen karşılaştırma)

| Seçenek | Nerede? | Karar | Gerekçe |
|---|---|---|---|
| **PostgreSQL** | Bulut (lisans, müşteri, ödeme) | ✅ Kullanılıyor | Kısıtlar ve tetikleyicilerle iş kurallarını veritabanında da zorlayabiliyoruz (ör. cihaz limiti, tek seferlik lisans tahsisi, değiştirilemez denetim kaydı). Yönetilen hizmeti her bulut sağlayıcısında var. |
| **SQLite** | Kullanıcının bilgisayarı (emirler, pozisyonlar, karar günlüğü, ayarlar) | ✅ Kullanılıyor | Kurulum gerektirmez, tek dosya, WAL ile çökmeye dayanıklı. Motor tek yazar olduğu için ölçek sorunu yok. |
| **Redis** | Bulut | ✅ Kullanılacak (Aşama 13/15) | Hız sınırlama, oturum iptal listeleri, aktarma servisinde pub/sub. Kalıcı kayıt tutmaz. Masaüstünde **gerek yok**: süreç içi bellek yeterli. |
| **ClickHouse** | — | ❌ Şimdilik hayır | Sunucu süreci gerektirir; Windows'ta yerel resmi destek yok; son kullanıcı bilgisayarına kurdurulması ağır ve kırılgan olur. Yerel analitik için DuckDB aynı sütun tabanlı faydayı gömülü olarak verir. İleride bulutta **ürün telemetrisi** analizi gerekirse (on binlerce cihaz) yeniden değerlendirilecek. |
| **DuckDB + Parquet** | Kullanıcının bilgisayarı (tarihsel mum/işlem verisi) | ✅ Kullanılacak (Aşama 5) | Yüz milyonlarca satırı sıkıştırılmış sütunlu dosyalarda tutar; vektörize sorgular; tek dosyalık gömülü kütüphane. |

## Ayrıntılı gerekçeler

### İşlem motoru: Python (Rust yardımıyla)

* **Neden Python:** Yapay zekâ (PyTorch, LightGBM, scikit-learn), veri işleme (numpy,
  polars), istatistik ve geriye dönük test araçlarının neredeyse tamamı Python'da. Strateji
  geliştirme hızı ürün değerinin ana kaynağı.
* **Performans gerçekçiliği:** Binance verisinin büyük kısmı 100 ms - 1 sn aralığında gelir.
  `msgspec` ile JSON çözümleme mikro saniyeler düzeyindedir. Ölçülen olay veri yolu hızı bu
  ortamda tek abonede ~720 bin olay/sn; gereksinimin çok üzerinde.
* **Rust ne zaman:** Profil ölçümü gösterirse yalnızca sıcak yollar (emir defteri bakımı,
  gösterge hesapları) PyO3 modülüne taşınır. Baştan Rust ile yazmak geliştirme hızını
  düşürür, kazancı belirsizdir.
* **Paketleme:** Nuitka (C'ye derleme, tersine mühendisliği zorlaştırır) veya PyInstaller ile
  tek klasörlük sidecar; Authenticode ile kod imzalama (onay kapısı G6).

### Yapay zekâ: PyTorch + LightGBM, çıkarım ONNX Runtime

Piyasa özellikleri büyük ölçüde tablo verisidir; gradyan artırmalı ağaçlar bu veride
genellikle güçlü bir temel çizgidir. PyTorch dizi modelleri (ör. zaman serisi
dönüştürücüleri) için kullanılır. Üretimde modeller ONNX'e aktarılır: kurulum boyutu
(PyTorch yüzlerce MB) ve çıkarım gecikmesi düşer. Aşırı uyum (overfitting) riskine karşı:
zaman sıralı ve arındırılmış (purged) çapraz doğrulama, walk-forward testi, sanal işlemde
bekleme süresi. Hiçbir model kazanç garantisi vermez.

### Masaüstü: neden Tauri 2 (C#/.NET yerine)?

| Kriter | Tauri 2 + React | .NET (WPF / WinUI 3) | Electron |
|---|---|---|---|
| Profesyonel finans grafikleri | Lightweight Charts (Apache-2.0, ücretsiz) | Ticari grafik kütüphaneleri genellikle ücretli lisans ister | Lightweight Charts |
| Web sitesiyle ortak kod | Evet (React bileşenleri, tipler) | Hayır | Evet |
| Kurulum boyutu / bellek | Küçük (sistem WebView2) | Orta | Büyük (Chromium paketlenir) |
| Güvenlik modeli | Rust kabuk, izin tabanlı API | İyi | Daha geniş saldırı yüzeyi |

**Not:** Lightweight Charts lisansı, uygulamada TradingView'a atıf bağlantısı gösterilmesini
ister; arayüzde buna yer ayrılacak.

### iOS: SwiftUI

Secure Enclave'de üretilen ve cihazdan çıkarılamayan anahtar, uzaktan komut imzalamanın
temelidir; bu ancak yerel uygulamayla mümkündür. Face ID ile hassas komut onayı, APNs ve
arka plan davranışları yerel API'lerle güvenilir şekilde yönetilir.

### Web: Next.js + TypeScript

Pazarlama sayfaları için SEO ve hız; müşteri/yönetici panelleri için aynı kod tabanı.
Yönetici paneli ayrı alt alan adında yayınlanır, ayrı çerez kapsamı ve ayrı API yönlendiricisi
kullanır.

### Bulut: FastAPI + PostgreSQL + SQL-öncelikli geçişler

ORM'nin otomatik ürettiği geçişler yerine elle yazılmış, gözden geçirilebilir SQL:
güvenlik açısından kritik kısıtlar (lisans durum makinesi, cihaz limiti, denetim zinciri)
doğrudan okunabilir ve gerçek PostgreSQL üzerinde test edilir. Geçiş çalıştırıcısı özet
doğrulaması ve advisory lock kullanır.

### Ödeme sağlayıcısı (karar bekliyor, onay kapısı G3)

| Seçenek | Artı | Dikkat |
|---|---|---|
| **Paddle / Lemon Squeezy** (Merchant of Record) | Küresel KDV/satış vergisini sağlayıcı üstlenir; yazılım satışı için kurgulanmış | Komisyon daha yüksek; "işlem yazılımı" kategorisinin kabulü önceden teyit edilmeli |
| **Stripe** | Geniş ödeme yöntemi, güçlü webhook altyapısı | Türkiye'de doğrudan hesap açma durumu ve yasaklı iş türleri listesi teyit edilmeli |
| **iyzico / PayTR** | Türk kartları, TL, taksit | Yurt dışı müşteriler için sınırlı; e-Arşiv fatura entegrasyonu ayrıca gerekir |

Kod tarafında `PaymentProvider` arayüzü tanımlanacak; webhook imzası doğrulanmadan hiçbir
olay işlenmeyecek (şemada `webhook_processed_requires_valid_signature` kısıtı).

### Zincir üstü balina verisi (karar bekliyor, onay kapısı G4)

Binance kaynaklı balina sinyalleri (büyük `aggTrade` işlemleri, emir defteri duvarları,
tasfiye akışı, büyük oyuncuların long/short oranları) ek maliyet olmadan Aşama 4'te gelir.
Zincir üstü transferler ve borsa giriş/çıkışları için etiketli cüzdan verisi gerekir;
seçenekler ücretsiz/kotalı blok gezgini API'lerinden ücretli analitik sağlayıcılara kadar
uzanır. Ücretli bir sağlayıcı seçilmeden önce onayınız alınacak. Yalnızca herkese açık
blokzincir verisi ve yetkili API'ler kullanılır; kimsenin özel hesabına erişilmez.
