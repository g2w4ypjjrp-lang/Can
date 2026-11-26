# FAZ 7 raporu — SEO, çok dilli içerik ve Etsy ilan oluşturma

## Ne yapıldı

| Özellik                                               | Nasıl çalışır                                                                                                                                                                                                          | Etsy / Printify işlemi (yalnızca onaydan sonra)                                                                              |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **AI SEO önerisi** (ilan veya Printify ürünü)         | Claude başlık, açıklama, 13 etiket, malzeme önerir; mağazanın **gerçek Etsy anahtar kelime verisi** (FAZ 5) kullanılır; ardından deterministik Etsy kural/spam kontrolü; hata varsa **bir onarım turu**                | Etsy ilanı: `updateListing` (PATCH). Printify ürünü: `PUT product` + Etsy’deyse yalnız başlık/açıklama/etiket yeniden yayını |
| **Elle düzenleme + canlı kontrol**                    | Her kayıtta kurallar yeniden çalışır; hatalı öneri onaya gönderilemez                                                                                                                                                  | —                                                                                                                            |
| **Çok dilli içerik** (de, fr, es, it, pt, nl, pl, ja) | Claude yerelleştirir (etiketler hedef dilde yeniden araştırılır) + **geri çeviri** + yerelleştirme notları; kalite kontrolü: Etsy kuralları, **sayılar korunmuş mu**, ürün üzerindeki metin korunmuş mu, uzunluk oranı | `createListingTranslation` (POST) veya mevcutsa `updateListingTranslation` (PUT)                                             |
| **İnsan incelemesi**                                  | Çeviri “İnceledim, doğru” işaretlenmeden onaya gönderilemez                                                                                                                                                            | —                                                                                                                            |
| **Yeni Etsy ilanı**                                   | Kategori arama (Etsy satıcı taksonomisi), mağazanın kargo profili / iade politikası / üretim ortakları (Etsy senkronizasyonunda alınır)                                                                                | `createDraftListing` → Etsy’de **TASLAK** (alıcıya görünmez, ilan ücreti yayınlanınca)                                       |

## Kurallar (resmî Etsy Open API v3 şemasından doğrulandı)

- Başlık: `/[^\p{L}\p{Nd}\p{P}\p{Sm}\p{Zs}™©®]/u` geçersiz; `% : & +` en fazla birer kez; 140 karakter.
- Etiket: `/[^\p{L}\p{Nd}\p{Zs}\-'™©®]/u` geçersiz; 13 etiket, 20 karakter. Malzeme: yalnız harf/rakam/boşluk.
- `createDraftListing` zorunlu alanları: quantity, title, description, price, who_made, when_made, taxonomy_id; fiziksel üründe `shipping_profile_id`.
- Spam/kalite kontrolleri: aynı kelimenin 2’den fazla tekrarı (hata), BÜYÜK HARF, kanıtlanamayan ifadeler (“best seller”, “#1”, “free shipping”…),
  etiketlerde tekrar ve aynı kelimenin 4’ten fazla etikette kullanılması, kısa açıklama, ana ifadenin konumu, korumalı terimler (marka/karakter).
- **“Başkası yaptı”** yalnız malzeme veya vintage ürünlerde kabul edilir; Printify ürünleri için **doğrudan ilan oluşturma reddedilir** (Printify yayını
  ilanı zaten oluşturur — çift ilan önlenir).
- Etsy yaratıcılık standartları gereği: AI ile üretilmiş tasarımlarda açıklamaya AI kullanım beyanı, Printify ürünlerinde üretim ortağı satırı eklenir.

## Doğrulanmamış / dikkat

- Form gövdesinde dizi alanları (`tags`, `materials`, `production_partner_ids`) **virgülle** gönderiliyor (şema `tags` için bunu yazıyor; diğerleri
  için şema kodlama belirtmiyor). Canlı anahtarla ilk `createDraftListing` çağrısında doğrulanmalı.
- Görseller taslak ilana yüklenmiyor (Etsy’de eklenir); yayınlama ayrı bir işlem.
- Çeviri kalitesi otomatik kontrol + geri çeviri + insan incelemesi ile korunur; dil bilgisi uzmanı onayı yerine geçmez.

## Veritabanı

Migration `0018`: `seo_drafts` (RLS: görüntüleyici okur, yönetici yazar), çeviri kalite/geri çeviri/inceleme/yayın alanları, onay türleri
`create_listing` ve `update_listing_translation`, ilan alanları (iade politikası, üretim ortakları, tür).

## Testler

Unit 139 · Integration 122 · E2E 16 — hepsi geçti. Yeni: kural denetleyicisi ve çeviri olgu kontrolleri (unit), SEO/çeviri/taslak ilan/Printify SEO
akışları ve onarım turu (integration), arayüzde SEO → onay → Etsy ve çeviri → inceleme → onay → Etsy (E2E). Etsy, Printify ve Claude resmî
sözleşmeye göre yazılmış test sunucularıyla çalıştı.

## Benden gerekenler

`ANTHROPIC_API_KEY`, Etsy anahtarları (`listings_w` kapsamı zaten isteniyor). Mağaza dilleri: Ayarlar → Diller.
