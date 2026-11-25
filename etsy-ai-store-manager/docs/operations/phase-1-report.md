# FAZ 1 raporu

## Çalışan özellikler

- Kayıt / giriş / çıkış (Supabase Auth), korumalı panel, e-posta doğrulama callback'i
- Mağaza kaydı oluşturma (Etsy bağlantısı FAZ 2'ye kadar `not_connected`)
- Genel bakış: ciro, sipariş, ortalama sepet, reklam harcaması, ROAS, iade oranı, ülke/ürün kırılımı,
  bekleyen onaylar, entegrasyon durumu — **yalnızca veritabanındaki gerçek kayıtlardan**; veri yoksa açıkça "bağlı değil"
- Ayarlar: kişisel ayarlar, satış stratejisi, AI yetki seviyesi, mağaza dilleri, hedef pazarlar, günlük reklam
  bütçe sınırı, kâr politikası (hedef 10 USD; 15/10/7/0 eşikleri, rezerv oranları) — hepsi düzenlenebilir ve denetim kaydına yazılır
- Bildirimler (listeleme, okundu işaretleme)
- 17 maddelik menü; henüz geliştirilmemiş modüller sahte veri yerine faz durumunu gösterir
- Worker: heartbeat ve süresi geçen onayları kapatma işleri; retry + idempotency
- PWA (manifest, service worker — finansal veriyi önbelleğe almaz), mobil menü
- Swagger: `/docs`, makinece okunur şema: `docs/api/openapi.json`

## Veritabanı

41 zorunlu tablo + `store_members` (çoklu kullanıcı/SaaS için). 12 migration; gerçek Supabase CLI yığınında
(Auth + Storage dahil) hatasız uygulandı. Storage bucket'ları: `designs`, `mockups`, `store-assets` (özel).

## Testler (hepsi geçti)

| Paket       | Sayı | Kapsam                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------- | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit        | 48   | para/ondalık karşılaştırma, ayar şemaları, eşik sırası, menü, JWT doğrulama (sahte imza, yanlış issuer/audience, anon/service_role, süresi dolmuş, alg=none), AES-GCM token şifreleme (AAD, kurcalama, anahtar sürümü), env doğrulama, worker yardımcıları                                                                                                                                                                                                                                           |
| Integration | 51   | 41 tablo, her tabloda RLS, FK indeksleri, float yasağı, migration idempotency ve değiştirilmiş migration tespiti, DB kısıtları; RLS: kiracı izolasyonu, viewer salt okuma, PII gizleme, token tablosuna erişim yok, anon erişimi yok, sahiplik devri engeli, append-only audit; API: 401/403/404/429, güvenlik başlıkları, mass-assignment engeli, audit kaydı, dashboard kesin ondalık toplamları; worker: tek sefer çalışma, retry, eşzamanlı kopya, kira geri alma, gerçek Redis ile BullMQ retry |
| E2E         | 8    | gerçek Supabase Auth + API + RLS + Next.js production build: yönlendirme, hatalı parola, kayıt→mağaza→dashboard, 17 menü, ayar/kâr politikası kaydı ve hatalı eşik reddi, çıkış, PWA, mobil                                                                                                                                                                                                                                                                                                          |

Testlerin yakaladığı ve düzeltilen gerçek hatalar: eşzamanlı iş kopyalarının iki kez çalışması (kira eklendi);
`numeric(12,4)` alanlarının 2 ondalık doğrulamasına takılıp ayarların kaydedilememesi; Next.js 16.4.3 ve zod 4.3.5
güvenlik açıkları (16.4.6 / 4.6.7'ye yükseltildi; `pnpm audit`: açık yok).

## Eksik entegrasyonlar

Etsy, Printify, Claude, reklam platformları — henüz bağlı değil (FAZ 2, 3, 5, 8).

## Gerekli anahtarlar (yalnızca sunucu `.env`'ine)

- FAZ 1 production: Supabase proje URL'si, publishable/anon key, veritabanı pooler bağlantı dizesi
- FAZ 2: Etsy uygulaması **keystring** ve **shared secret** + kayıtlı callback URL
- FAZ 3: Printify kişisel erişim belirteci
- FAZ 5: Anthropic API anahtarı
- FAZ 6: görsel üretim sağlayıcısı seçimi ve anahtarı
