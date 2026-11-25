# FAZ 2 raporu — Etsy entegrasyonu

## Doğrulanan resmî kaynaklar (2026-11-25)

- developers.etsy.com: Authentication, Requests, Rate Limits, Listings tutorial
- Resmî OpenAPI şeması: `https://www.etsy.com/openapi/generated/oas/3.0.0.json` (uç noktalar, kapsamlar,
  `Money`, `ShopReceipt`, `ShopListing`, `updateListing` alanları programla çıkarıldı)

Uygulanan sözleşme:

| Konu            | Değer                                                                                               |
| --------------- | --------------------------------------------------------------------------------------------------- |
| Yetkilendirme   | `https://www.etsy.com/oauth/connect`, `response_type=code`, PKCE **S256 zorunlu**, `state`          |
| Token           | `POST https://api.etsy.com/v3/public/oauth/token` (form-urlencoded); erişim 1 saat, yenileme 90 gün |
| Başlıklar       | `x-api-key: <keystring>:<shared_secret>`, `Authorization: Bearer <user_id>.<token>`                 |
| Kapsamlar       | `shops_r listings_r listings_w transactions_r` (en az yetki; silme/kargo yazma istenmedi)           |
| Hız limiti      | 429 + `retry-after`; `x-remaining-this-second`, `x-remaining-today` başlıkları izlenir              |
| Sayfalama       | `limit` ≤ 100, `offset`                                                                             |
| İlan güncelleme | `PATCH /v3/application/shops/{shop_id}/listings/{listing_id}`, form-urlencoded, etiketler virgülle  |

## Çalışan özellikler

- **Bağlantı:** Mağaza sahibi "Etsy ile bağlan" → Etsy onayı → geri dönüş. State tek kullanımlık ve 10 dakika
  geçerli (yalnızca SHA-256'sı saklanır); PKCE doğrulayıcısı şifreli. Token'lar AES-256-GCM ile hesaba bağlı
  (AAD) şifreli. Aynı Etsy mağazası iki ayrı kayda bağlanamaz.
- **İçe aktarma (worker):** mağaza bilgisi; tüm ilanlar (aktif, taslak, pasif, süresi dolmuş, tükenmiş;
  görsellerle, sayfalı); siparişler (receipt + transaction + kargo + iade kayıtları) artımlı
  (`min_last_modified`, 24 saat örtüşme). Para birimi tam ondalık (float yok); KDV vergiye dahil;
  **alıcı e-postası saklanmaz** (veri minimizasyonu). Her 6 saatte otomatik, istenirse elle.
- **Token yenileme:** süresi dolmaya 5 dk kala otomatik; satır kilidiyle eşzamanlı yenileme engellenir;
  yenileme başarısızsa bağlantı "yeniden bağlanmalı" olur ve yöneticilere bildirim gider.
- **İlan değişikliği (onaylı):** başlık / açıklama / etiket / malzeme / aktif-pasif. Önce onay isteği oluşur
  (ne, neden, fayda, maliyet, kâr etkisi, API işlemi). Onay hassas işlemde **parolayla yeniden doğrulama**
  ister. Yürütmeden önce ilan Etsy'den yeniden okunur; öneriden sonra Etsy'de değişmişse **üzerine yazılmaz**
  (çakışma raporlanır). Yalnızca değişen alanlar gönderilir, diğer tüm ilan verisi korunur.
- **Bağlantıyı kesme:** token'lar silinir, içe aktarılan veri korunur.
- **Dashboard:** bağlantı kurulunca gerçek siparişlerden "Canlı veri" gösterir.
- **API'nin izin vermediği işlemler** (resmî şemada yok, otomatikleştirilmedi): Etsy Ads kampanya
  yönetimi, alıcı mesajlaşma, iade başlatma, sipariş iptali, mağaza logo/banner yükleme.

## Veritabanı

Migration `0013`: `oauth_states` (yalnızca sunucu erişimi), `listings` ek alanları (Etsy URL, ana görsel,
Etsy güncellenme zamanı), kargo/iade tekrar-önleme indeksleri.

## Testler

| Paket       | Sayı     | Yeni kapsam                                                                                                                                                                                                                                                                                        |
| ----------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit        | 76 (+28) | Money→ondalık, PKCE (RFC 7636 test vektörü), yetkilendirme URL'si, durum eşlemesi, KDV, e-posta dışlama, 429/retry-after, sayfalama, form PATCH, 401/403, anahtar rotasyonu, Etsy başlık/etiket kuralları                                                                                          |
| Integration | 68 (+17) | OAuth (sahte state, tekrar kullanım), şifreli token, 102 ilan/3 sipariş içe aktarma, kesin tutarlar, tekrar senkronizasyonda idempotency, süresi dolmuş token yenileme, rol kontrolleri, onay + yeniden doğrulama, yalnızca değişen alanların gönderilmesi, çakışmada yazmama, red, bağlantı kesme |
| E2E         | 11 (+3)  | Tarayıcıda: bağlan → OAuth → içe aktarma → ilan değişikliği → yanlış/doğru parola → Etsy'de uygulama → bildirim                                                                                                                                                                                    |

**Önemli:** Etsy tarafı testlerde, resmî şemaya göre yazılmış bir **sözleşme test sunucusuyla**
(`tests/helpers/etsy-stub.ts`) doğrulandı. Gerçek Etsy API'siyle canlı doğrulama, sizin uygulama
anahtarlarınızla yapılacak.

## Benden gerekenler

1. Etsy geliştirici portalında bir uygulama oluşturun ve **keystring** ile **shared secret** alın.
2. Callback URL olarak `https://<alan-adınız>/api/v1/integrations/etsy/callback` kaydedin (https, birebir aynı).
3. Sunucu `.env`: `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`, `ETSY_REDIRECT_URI`, `WEB_APP_URL`.
4. Panelde **Etsy Mağazam → Etsy ile bağlan**. İlk içe aktarma otomatik başlar; mağazanızda hiçbir değişiklik
   yapılmaz. İlan değişiklikleri yalnızca sizin onayınızla uygulanır.

Not: Etsy yeni uygulamaları kişisel erişimle başlatıp ticari/genişletilmiş erişim için ayrıca inceleme
isteyebilir; kendi mağazanız için kişisel erişim yeterli olmalıdır (portalda kontrol edin).
