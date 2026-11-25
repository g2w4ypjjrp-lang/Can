# FAZ 5 raporu — AI pazar araştırması ve ürün fırsatları

## Veri kaynakları ve dürüstlük kuralları

| Kaynak                                                                                                          | Ne verir                                                                                                                                                           | İşaret                                                                           |
| --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| **Etsy Open API v3 `findAllListingsActive`** (yalnızca API anahtarı, OAuth gerekmez — resmî şemadan doğrulandı) | Aktif ilan sayısı (arz), fiyat dağılımı (USD'ye ECB kuruyla çevrilir), ilan başı ortalama favori, son 90 günde açılan ilan oranı, sık etiketler, ilk 10 rakip ilan | **Gerçek veri** (`is_estimate=false`)                                            |
| **Claude web araması** (`web_search_20260209`, isteğe bağlı)                                                    | Trend, hediye günleri, sezon; her bulgu URL ile                                                                                                                    | Tahmin; kaynak URL zorunlu                                                       |
| **Claude analizi** (`claude-opus-5-5`, Zod şemalı yapılandırılmış çıktı)                                        | Fırsat fikirleri, hedef müşteri, etiketler, önerilen fiyat, IP riski                                                                                               | Tahmin; verilmeyen bir URL'ye atıf yapan sinyal otomatik "doğrulanmamış" yapılır |

- Etsy rakip satış adedi/geliri vermez; sistem bunları **asla** gerçek gibi göstermez (sistem istemi + şema + arayüz etiketleri).
- Model yalnızca **özgün** tasarım fikri önerir; marka/karakter/ünlü içerenler **yüksek IP riski** ile otomatik elenir.

## Kârlılık ve puan

- Her fırsatın katkısı **Profit Engine** ile hesaplanır (önerilen fiyat, mağazadaki aynı ürün tipinin güncel Printify üretim +
  hedef ülke kargo maliyeti, Etsy ücretleri, sipariş başı reklam payı). Maliyet bilinmiyorsa katkı gösterilmez ("bilinmiyor").
- **Zarar** eden fikirler otomatik elenir (spec: kâr hedefini karşılamayanları ele).
- **Fırsat puanı** deterministiktir (yapay zekâ vermez): `35×kâr + 35×(düşük rekabet) + 30×(ilgi) − IP cezası`; bileşenler kaydedilir ve
  arayüzde gösterilir. Kâr bileşeni katkı/(2×hedef), rekabet `1 − log10(ilan sayısı)/6`, ilgi `log10(1+ort. favori)/log10(201)`.

## Claude API kullanımı

- `@anthropic-ai/sdk` 1.14.0, model `claude-opus-5-5`, `output_config.effort: medium`, düşünme varsayılan (adaptif).
- Web araştırma çağrısında **sunucu tarafı yedek model** açık (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`):
  model güvenlik nedeniyle reddederse istek uygun modelle otomatik tekrarlanır. İsterseniz kapatabilirim.
- `pause_turn` (sunucu araç döngüsü sınırı) 4 kez otomatik sürdürülür; `refusal` temiz biçimde hata olarak kaydedilir.
- Her görevin token kullanımı ve **tahmini maliyeti** `ai_tasks` tablosuna yazılır ve arayüzde gösterilir (Opus 5.5: $4/$20 / 1M token;
  web araması ayrıca ücretlendirilir).
- Anahtar yoksa yalnızca Etsy verisi kaydedilir, fırsat **uydurulmaz**.

## Veritabanı

Migration `0016`: araştırma ülke/web/hata alanları, anahtar kelime pazar metrikleri, fırsat ürün tipi/IP/gerekçe/karar/puan dökümü.

## Testler

Unit 114 · Integration 97 · E2E 14 — hepsi geçti. Etsy ve Claude, resmî sözleşmeye göre yazılmış test sunucularıyla
(`tests/helpers/etsy-stub.ts`, `tests/helpers/anthropic-stub.ts`) doğrulandı; gerçek SDK test sunucusuna bağlanır.
Testlerin yakaladığı uyumsuzluk: SDK 1.14 anahtarı `Authorization: Bearer` ile gönderiyor (API sürümü 2026-10-21) — test sunucusu güncellendi.

## Benden gerekenler

`ANTHROPIC_API_KEY` (worker ve API `.env`). Pazar verisi için Etsy `ETSY_KEYSTRING` + `ETSY_SHARED_SECRET` yeterli (OAuth gerekmez).
