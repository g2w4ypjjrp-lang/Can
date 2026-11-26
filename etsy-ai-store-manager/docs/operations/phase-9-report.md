# FAZ 9 raporu — Siparişler, müşteriler, kargo, iadeler

## Resmî Etsy Open API v3 durumu (yerel OAS şemasından doğrulandı)

| İşlem                                     | API                                                        | Bu platformda                                                                                                  |
| ----------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Siparişler, kalemler, Etsy iade kayıtları | `getShopReceipts` (`transactions_r`)                       | Senkronize (FAZ 2)                                                                                             |
| Takip numarası + alıcı bildirimi          | `createReceiptShipment` (`transactions_w`, **JSON** gövde) | **Onaylı otomatik** yürütme. Printify siparişlerinde reddedilir (Printify kendisi iletir; çift bildirim olmaz) |
| Mağaza yorumları                          | `getReviewsByShop` (yalnız API anahtarı)                   | Senkronize. `ListingReview`'de yorum kimliği yok; anahtar (ilan, oluşturulma zamanı)                           |
| Müşteri mesajları                         | **Yok**                                                    | Mesajı yapıştırırsınız → AI taslak → onay → Etsy'de elle gönderim → "Uyguladım"                                |
| İade                                      | **Yok**                                                    | Onay (kâr etkisiyle) → Etsy panelinde iade → "Uyguladım". Kâr yeniden hesaplanır                               |
| Sipariş iptali                            | **Yok**                                                    | Onay → Etsy (+ Printify) panelinde iptal → "Uyguladım"                                                         |

Yeni OAuth kapsamı: **`transactions_w`**. Mevcut bağlantılar yeniden bağlanmalı. Kapsam yoksa yürütme açık bir mesajla başarısız olur ve hiçbir şey gönderilmez.

## Özellikler

- **Sipariş listesi**: filtreler (gönderilmemiş, geciken, sorunlu, sipariş no), Printify üretim durumu, kargolar, sipariş başı katkı ve karar rozeti.
- **Gecikme tespiti**: mağazanın hazırlık/kargo eşikleri (varsayılan 7/21 gün, panelden değişir). Geciken kargolar `delayed` olur.
  Günde en fazla bir bildirim gönderilir.
- **AI triage** (`claude-opus-5-5`, Zod şemalı):
  - kategori, duygu, aciliyet (hukuki tehdit / chargeback = kritik), sorunlar, önerilen işlem, Türkçe iç not
  - müşterinin dilinde **yanıt taslağı**, yalnız sistemdeki sipariş gerçeklerine dayanır (gerçek takip numarası, durum)
  - iade / yeniden gönderim / indirim **vaat etmez**
  - Düşük puanlı (≤3★) yorumlar otomatik triage'a girer. Yanıt herkese açık yorum yanıtı olarak işaretlenir. **Hiçbir şey otomatik gönderilmez.**
- **İade onayı**: siparişin saklı Profit Engine girdisi önerilen iadeyle yeniden hesaplanır. Onayda katkı "önce → sonra" gösterilir (işlem ücreti
  orantılı iade edilir, diğer ücretler ve üretim maliyeti geri gelmez). Sipariş tutarını aşan iade reddedilir.
- **Müşteriler**: sipariş sayısı, gelir, tekrar alan oranı, açık konular. Müşteri verisi ve mesajlar **yalnız yöneticilere** açıktır (RLS + API).

## Bu fazda düzeltilen üretim hatası

API hız sınırı istemci IP'sine göre çalışıyordu. Panel API'yi kendi sunucusundan çağırdığı için tüm kullanıcılar tek bir sınırı paylaşırdı.
Artık anahtar oturum jetonunun özetidir; jetonsuz istekler IP ile sınırlanır, Nginx de uçta sınırlar. Birim testi eklendi.

## Veritabanı

Migration `0020`:

- `shop_reviews` tablosu
- `customer_messages` triage alanları: kaynak, yorum bağı, aciliyet, sorunlar, önerilen işlem, iç not, AI görevi
- iade kâr etkisi alanları
- gecikme eşikleri
- gönderi kaynağı
- onay türü `add_tracking`

## Testler

Unit 151 · Integration 138 · E2E 18 — hepsi geçti. Etsy ve Claude sözleşme test sunucularıyla:

- yorum senkronizasyonu ve triage
- filtreler ve gecikme
- takip numarası: kapsam yokken red, Printify siparişinde red, onay sonrası gönderim
- iade: fazla iade reddi, kâr etkisi, manuel onay, kısmi iade durumu
- yapıştırılan mesaj: sipariş gerçeklerine dayalı taslak, onay, gönderildi işareti
- müşteri verisine yetki

## Doğrulanmamış / dikkat

- `createReceiptShipment` gövdesi şemaya göre JSON. Canlı anahtarla ilk çağrıda doğrulanmalı.
- `getReviewsByShop` yanıtında yorum kimliği olmadığından, aynı saniyede aynı ilana yazılan iki yorum tek kayıt sayılabilir. Bu düşük olasılıklı bir sınırlamadır.
