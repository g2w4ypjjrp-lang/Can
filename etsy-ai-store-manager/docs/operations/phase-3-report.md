# FAZ 3 raporu — Printify entegrasyonu

## Doğrulanan resmî kaynak (2026-11-25)

https://developers.printify.com/ — kimlik doğrulama, hız limitleri, katalog, ürünler, siparişler, webhook'lar.

| Konu             | Uygulanan                                                                                                     |
| ---------------- | ------------------------------------------------------------------------------------------------------------- |
| Kimlik doğrulama | Kişisel erişim token'ı, `Authorization: Bearer`, zorunlu `User-Agent`; token 1 yıl geçerli                    |
| Limitler         | 600 istek/dk (genel), katalog +100/dk, yayınlama 200/30 dk → katalog sunucuda önbellekli, 429'da geri çekilme |
| Para             | Tam sayı kuruş → tam ondalık (float yok)                                                                      |
| Webhook          | `X-Pfy-Signature: sha256=<HMAC-SHA256(ham gövde)>`, sabit zamanlı karşılaştırma                               |
| Yayınlama        | `POST /v1/shops/{shop_id}/products/{product_id}/publish.json` → Printify bağlı Etsy mağazasına gönderir       |

## Çalışan özellikler

- **Bağlantı:** token'daki Printify mağazaları listelenir (satış kanalıyla); Etsy'ye bağlı olan önerilir. Token
  yalnızca sunucu `.env`'inde. Webhook gizli anahtarı ve https adresi varsa 11 webhook konusu otomatik kaydedilir.
- **Ürün senkronizasyonu:** ürünler, varyantlar, satış fiyatı, **üretim maliyeti** (`variants[].cost`),
  **kargo maliyetleri** (ilk/ek ürün; ülke ve "dünyanın geri kalanı" bazında), mockup görselleri, Etsy ilan
  bağlantısı (`external.id`). Maliyetler **sürümlüdür**: değişen maliyet eski kaydı kapatır, yenisini ekler ve
  yöneticilere bildirim gider (maliyet geçmişi ürün sayfasında).
- **Sipariş bağlantısı:** Printify siparişleri Etsy siparişleriyle (`metadata.shop_order_id` = receipt id)
  eşleştirilir: üretim durumu, gerçek üretim + kargo maliyeti, kargo takip numarası/URL'si.
- **Sağlayıcı karşılaştırması:** ürün tipi araması, seçili ülkeye kargo (ilk/ek), üretim süresi, konum, varyant
  sayısı. _Not:_ Printify kataloğu üretim maliyeti vermez; maliyet ürün oluşturulunca görünür (ekranda belirtiliyor).
- **Etsy'de yayınlama:** yalnızca onayla (yüksek risk, parolayla yeniden doğrulama). Onay kartında satış fiyatı ve
  üretim maliyeti aralığı gösterilir. Kilitli (yayın sürüyor) ürünler için istek reddedilir.
- **Webhook alıcısı:** imza doğrulanır, her olay bir kez saklanır (tekrarlar yok sayılır), mağaza yeniden senkronize edilir.

## Belirsiz nokta ve çözümü

Printify belgeleri sipariş kalemindeki `cost` alanının **birim** mi **satır toplamı** mı olduğunu yazmıyor. Sistem bunu
ilk çok adetli siparişte varyant maliyetiyle karşılaştırarak **otomatik tespit eder** ve kaydeder; o zamana kadar
"doğrulanmamış (birim varsayımı)" olarak işaretli gösterir.

## Veritabanı

Migration `0014`: `printify_catalog_cache`, `webhook_events` (yalnızca sunucu), ürün/sipariş/sipariş kalemi Printify alanları.

## Testler

Unit 86 · Integration 77 · E2E 12 — hepsi geçti. Printify tarafı resmî dokümana göre yazılmış **sözleşme test
sunucusuyla** (`tests/helpers/printify-stub.ts`) doğrulandı; canlı doğrulama token'ınızla yapılacak.
Testlerin yakaladığı hata: varyant başına yalnızca ilk kargo profili alınıyordu (uluslararası kargo maliyetleri
eksik kalıyordu) — düzeltildi.

## Benden gerekenler

- `PRINTIFY_API_TOKEN` (zorunlu), isteğe bağlı `PRINTIFY_WEBHOOK_SECRET` + https `API_PUBLIC_URL`.
