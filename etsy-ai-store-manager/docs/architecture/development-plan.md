# Geliştirme planı ve görev listesi

Durum: ✅ tamamlandı ve test edildi · 🟡 kısmen · ⬜ planlandı

## FAZ 1 — Temel altyapı ✅

- ✅ pnpm monorepo, TypeScript strict, ESLint, Prettier, Vitest (unit + integration), Playwright (E2E)
- ✅ Supabase migration'ları: 41 zorunlu tablo + `store_members`, FK/index/unique/check kısıtları, RLS, Storage bucket'ları
- ✅ Supabase Auth: kayıt, giriş, çıkış, e-posta doğrulama callback'i; API'de JWKS/HS256 doğrulama
- ✅ NestJS API: health/readiness, `/me`, mağazalar, mağaza ayarları, kâr politikası, dashboard, bildirimler, Swagger
- ✅ Audit log, rate limiting, token şifreleme servisi, hata filtresi, yapılandırılmış log (pino, request id)
- ✅ BullMQ worker: zamanlanmış işler, retry, idempotency, kira
- ✅ Next.js panel: 17 maddelik menü, genel bakış (yalnızca gerçek veri), ayarlar, bildirimler, PWA, mobil
- ✅ Docker (api/worker/web/migrate), Docker Compose, Nginx + HTTPS, şifreli yedekleme/geri yükleme

## FAZ 2 — Etsy ✅ (sözleşme testleriyle; canlı doğrulama anahtar bekliyor)

- ✅ Etsy Open API v3 OAuth 2.0 + PKCE, tek kullanımlık state, şifreli token, otomatik yenileme
- ✅ Mağaza, ilan (tüm durumlar, görseller, sayfalama) ve sipariş (receipt/transaction/kargo/iade) içe aktarma, artımlı ve idempotent
- ✅ Onaylı ilan düzenleme: yalnızca değişen alanlar, çakışma kontrolü, parolayla yeniden doğrulama
- ✅ API'de olmayan işlemler açıkça listelendi ve otomatikleştirilmedi
- ⬜ Canlı doğrulama: `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`, kayıtlı callback URL gerekli
- Ayrıntı: [phase-2-report](../operations/phase-2-report.md)

## FAZ 3 — Printify ✅ (sözleşme testleriyle; canlı doğrulama token bekliyor)

- ✅ Token ile bağlantı, mağaza seçimi, imzalı webhook'lar
- ✅ Ürün/varyant/üretim ve kargo maliyeti (sürümlü), mockup, Etsy ilan eşleşmesi
- ✅ Sipariş eşleştirme: üretim durumu, gerçek maliyet, kargo takibi
- ✅ Katalog ve baskı sağlayıcı karşılaştırması (önbellekli)
- ✅ Onaylı Printify → Etsy yayınlama
- Ayrıntı: [phase-3-report](../operations/phase-3-report.md)

## FAZ 4 — Profit Engine ⬜

- `packages/profit-engine`: Decimal, matrah bazlı ücret kuralları, ülke/para birimi farkları, döviz, iade/yeniden üretim rezervi, reklam dağıtımı (çift sayım yok), vergi öncesi/sonrası ayrımı, fiyat önerisi
- `fee_rules` yalnızca resmi kaynaktan doğrulanmış oranlarla doldurulacak
- Zorunlu 10 test senaryosu (≥10 USD, <10, negatif, reklam artışı, Printify maliyet değişimi, kargo değişimi, indirim, iade, farklı para birimi, farklı matrah)

## FAZ 5 — Pazar araştırması ⬜

- Claude API (structured output + tool calling); yalnızca erişilebilen veri kaynakları; her metrik `is_estimate` + güven seviyesi
- Gerekli: `ANTHROPIC_API_KEY`

## FAZ 6 — Tasarım stüdyosu ⬜

- Görsel üretim sağlayıcısı seçimi (Claude görsel üretmez; ayrı bir görsel modeli/servis gerekir — karar sizde)
- Baskı alanı/DPI kontrolü, arka plan kaldırma, versiyonlama, IP/marka risk kontrolü, insan katkısı kaydı

## FAZ 7 — SEO ve çok dilli içerik ⬜

## FAZ 8 — Reklam yönetimi ⬜

- Etsy Ads: kamuya açık resmi API bulunmadığı varsayımıyla yalnızca raporlama/CSV + onaylı manuel akış (faz başında doğrulanacak)
- Meta/Google/Pinterest/TikTok: resmi API erişimi onaylanan platformlarda kampanya yönetimi; toplam günlük bütçe sınırı zorunlu

## FAZ 9 — Sipariş, müşteri, kargo, iade ⬜

## FAZ 10 — AI Store Manager, otomasyon, raporlar, bildirimler ⬜

## FAZ 11 — Güvenlik, performans, production ⬜

## API kısıtları (her faz başında resmi dokümantasyonla yeniden doğrulanacak)

| Konu                       | Bilinen durum                                          | Uygulama yaklaşımı                                    |
| -------------------------- | ------------------------------------------------------ | ----------------------------------------------------- |
| Etsy rakip satış verisi    | Etsy rakip satış adetlerini API ile vermez             | Tahmin olarak işaretlenir, gerçekmiş gibi gösterilmez |
| Etsy Ads yönetimi          | Open API v3'te kampanya yönetimi uç noktası bilinmiyor | Raporlama + manuel onaylı iş akışı                    |
| Etsy müşteri mesajları     | Open API v3'te konuşma/mesaj uç noktası bilinmiyor     | Taslak hazırlanır, kullanıcı Etsy'de gönderir         |
| Etsy iade / sipariş iptali | API ile yapılamadığı biliniyor                         | Onaylı manuel iş akışı + takip kaydı                  |
| Etsy mağaza logosu/banner  | API desteği doğrulanacak                               | Öneri + manuel uygulama                               |
| Etsy AI politikası         | Satıcının yaratıcı katkısı ve doğru beyan gerekli      | `designs.human_contribution`, üretim ortağı beyanı    |
