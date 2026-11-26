# FAZ 6 raporu — AI Tasarım Stüdyosu

## Akış

`Fırsat (FAZ 5) veya boş tasarım` → **sizin yaratıcı yönlendirmeniz** (zorunlu, ≥20 karakter) → **AI ile SVG üretimi** veya **kendi dosyanız**
→ arka plan kaldırma (isteğe bağlı) → **baskı dosyası** (Printify baskı alanına 300 DPI) → **IP incelemesi** → **insan onayı**
→ **Printify'da taslak ürün** → (FAZ 3/4) kâr kontrollü yayın onayı.

## Görsel üretimi — gerçek durum

- Claude **piksel görsel üretmez**. Sistem Claude'dan (`claude-opus-5-5`, effort high, Zod şemalı çıktı) **SVG vektör tasarım** ister ve
  sunucuda `sharp` ile baskı çözünürlüğünde PNG'ye çevirir. Tipografi, çizgi çizim, rozet/amblem, düz grafik için uygundur.
- Fotoğraf gerçekliğinde görsel için **dosya yükleme** (PNG/JPEG/WebP/SVG, ≤25 MB, ≤8000×8000 px) kullanılır. Ayrı bir görsel üretim API'si
  (ör. bir difüzyon modeli) **bağlı değildir**; isterseniz sonraki fazlarda eklenebilir.
- **Mockup**: Printify ürün oluşturulduğunda kendi mockup görsellerini üretir ve ürün sayfasında görünür; sistem ayrı mockup üretmez.

## Güvenlik ve kurallar

- SVG güvenlik kontrolü: DOCTYPE/ENTITY, script, foreignObject, harici `href`/`url()`, `<image>`, `<use>`, olay öznitelikleri reddedilir
  (XXE/SSRF önlemi). Görseller boyut/piksel sınırlıdır.
- **IP kontrolü iki katmanlı**: (1) yerel korumalı terim taraması (marka/karakter/ünlü) — bulunursa risk **yüksek**, AI üretimi ve onay
  engellenir; (2) Claude görsel incelemesi (metin tespiti, benzerlik riski, öneri). **Hukuki görüş değildir.**
- Onay şartları (veritabanı ve API'de zorlanır): yaratıcı katkı metni, güncel sürüm için IP incelemesi, yüksek risk yok, baskıya hazır sürüm.
  Yeni sürüm yüklendiğinde/üretildiğinde onay ve IP incelemesi sıfırlanır.
- Etsy kuralları: AI destekli tasarımlarda satıcı katkısı kaydedilir; ilan oluştururken (FAZ 7) AI kullanımı ve üretim ortağı (Printify) beyanı eklenecek.
- Printify ürünü **taslak** olarak oluşturulur; Etsy'ye yayın yapılmaz. Yayın, mevcut kâr kontrollü onay akışından geçer.
- Dosyalar istemciye doğrudan açılmaz: panel, oturumlu bir sunucu rotası (`/files/designs/...`) üzerinden API'den alır; API mağaza üyeliğini kontrol eder.

## Veritabanı

Migration `0017`: tasarım–fırsat bağı, ürün tipi, stil, IP incelemesi, onaylayan; sürüm ağacı (parent), işlem tipi, baskı uyum raporu,
baskı alanı, AI görev bağı; `designs_ai_requires_human` kısıtı.

## API

`stores/:storeId/designs`: oluştur, listele, ayrıntı, yükle, üret (202), IP incelemesi (202), arka plan kaldır, baskıya hazırla, dosya,
durum (onay/red), Printify ürünü. Worker işleri: `design.generate`, `design.ip-review`.

## Depolama

`STORAGE_DRIVER=local` (VPS diski; yedeklemeye dahil edin) veya `supabase` (Storage `designs` kovası, service role anahtarı yalnızca sunucuda).

## Testler

Unit 131 · Integration 108 · E2E 15 — hepsi geçti. E2E: kayıt → Printify bağlantısı → tasarım → AI SVG üretimi → baskı dosyası →
IP incelemesi → onay → Printify taslağı (Claude ve Printify sözleşme test sunucularıyla).

## Eksik / bekleyen

- `ANTHROPIC_API_KEY` (gerçek üretim ve IP incelemesi için).
- Fotoğraf gerçekliğinde görsel üretim API'si bağlı değil (dosya yükleme ile çalışır).
- Printify baskı alanı kimlikleri (blueprint/sağlayıcı) şimdilik elle giriliyor; FAZ 7'de katalog seçiciye bağlanacak.
