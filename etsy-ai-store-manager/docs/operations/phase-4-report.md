# FAZ 4 raporu — Profit Engine

## Formül

**Net katkı = Net satış geliri − Toplam değişken giderler** (`packages/profit-engine`, Decimal, 28 hane; float yok).
Her hesap satır satır döküm (`breakdown`: matrah, oran, sabit ücret, kural kimliği) ile saklanır (`profit_snapshots`).

## Hesaba katılan kalemler

| Kalem                    | Kaynak / matrah                                                                                                                                                                         |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Listeleme/yenileme       | 0.20 USD × satılan adet (çok adetli satışta ek adet başına yenileme)                                                                                                                    |
| İşlem ücreti             | %6.5 × (ürün + kargo + hediye paketi − indirim)                                                                                                                                         |
| Ödeme işleme             | Banka ülkesine göre: US %3+0.25 USD, GB %4+0.20 GBP, DE/FR/ES/IT/NL %4+0.30 EUR, CA/AU yurt içi %3 / yurt dışı %4 (+0.25 yerel), **TR %6.5+14 TRY**; matrah vergi dahil sipariş toplamı |
| Döviz çevirme            | %2.5 (ilan ≠ ödeme para birimi)                                                                                                                                                         |
| Offsite Ads              | %15 / %12 (kademe ayarı), sipariş başı 100 USD tavan                                                                                                                                    |
| Düzenleyici işletim      | Satıcı ülkesine göre (TR %1.67, GB %0.48, FR %1.14, IT %0.80, ES %0.88, CA %0.50 …)                                                                                                     |
| Ücretler üzerindeki KDV  | Mağaza politikası (ülkenize göre siz girersiniz)                                                                                                                                        |
| Üretim + üretici kargosu | Printify gerçek sipariş maliyeti; yoksa güncel varyant maliyeti (tahmin olarak işaretli)                                                                                                |
| İade                     | Gerçek iade tutarı; ödeme işleme ücreti orantılı geri alınır (Help Center). İşlem ücretinin iadesi doğrulanamadı → iade edilmediği varsayılır (uyarı)                                   |
| Rezervler                | İade rezervi (simülasyon), yeniden üretim rezervi, diğer değişken giderler                                                                                                              |
| Reklam                   | Sipariş başı **dağıtım** (ayrı satır). Dönem kâr/zararında gerçek reklam harcaması (`ad_spend`) **bir kez** düşülür; dağıtım ikinci kez gider sayılmaz                                  |
| Vergi                    | Vergi öncesi katkı ile vergi sonrası tahmin ayrı                                                                                                                                        |

## Karar sistemi (panelden değiştirilebilir)

≥15 Çok iyi · ≥10 Yayınlanabilir · ≥7 Onay bekler · ≥0 Önerilmez · <0 Reddedilir.
**Yayın kapısı:** Zarar eden varyantı olan ürün için yayın isteği reddedilir; "önerilmez" seviyesi yalnızca açık onayla.
Eksik veri (satıcı ülkesi, maliyet, kur) varsa hesap "eksik" sayılır ve yayın isteği durdurulur.

## Ücret oranlarının doğrulanması

Etsy'nin resmî ücret politikası sayfası sunucudan **403** döndürdü; oranlar **Etsy Yardım Merkezi** makalelerinden alındı
ve **doğrulanmamış** olarak eklendi. Her mağaza sahibi Finans sayfasında oranları kendi Etsy ekstresiyle karşılaştırıp
"Doğrula" ile onaylar (mağaza bazında, denetim kaydıyla). Doğrulanmamış oran kullanılan her sonuç uyarı taşır.
Belirsiz noktalar: işlem ücreti matrahında satış vergisi (hariç varsayıldı), Macaristan düzenleyici oranı (kaynaklar çelişkili),
iade durumunda işlem ücreti (iade edilmez varsayıldı).

## Diğer

- **Döviz:** ECB günlük referans kurları (iş günleri 15:20 UTC), EUR çapraz kur; kur yoksa sonuç "eksik", tahmin yapılmaz.
- **Fiyat önerisi:** hedef katkıya ulaşan en düşük fiyat (kuruş hassasiyetinde ikili arama) + .99 ile biten öneri; onaylanırsa
  Printify varyant fiyatları güncellenir ve yalnızca varyantlar Etsy'ye yeniden yayınlanır.
- **Sipariş katkıları:** her Etsy/Printify senkronizasyonundan sonra yeniden hesaplanır (idempotent, siparişi yeniden yazar).

## Testler

Unit 114 (zorunlu 10 senaryo + iade, kur, matrah, karar, fiyat önerisi), Integration 89, E2E 13 — hepsi geçti.
Elle hesaplanan beklenen değerler test dosyasında açıklamalı: `tests/unit/profit-engine/scenarios.spec.ts`.

## Benden gerekenler

Ayarlar → Mağaza: **Etsy ödeme hesabı (banka) ülkesi**, **ödeme para birimi**; Kâr politikası: ücretler üzerindeki KDV oranı,
Offsite Ads kademesi. Ardından Finans sayfasında ücret oranlarını Etsy ekstrenizle doğrulayın.
