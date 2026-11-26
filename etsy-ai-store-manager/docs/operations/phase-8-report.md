# FAZ 8 raporu — Reklam Yönetimi

## Platform durumu (resmî dokümanlardan doğrulandı)

| Platform                      | Raporlama                                                                                                                 | Bütçe / kampanya yönetimi | Neden                                                                                                          |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Etsy Ads**                  | CSV/elle + **Etsy ödeme defterinden gerçek harcama** (`getShopPaymentAccountLedgerEntries`, `transactions_r`)             | Onaylı **manuel** adım    | Etsy Open API v3 şemasında reklam uç noktası yok (yerel OAS taraması).                                         |
| **Meta** (Facebook/Instagram) | **API**: Marketing API **v27.0** (2026-11-04), `GET /act_{id}/insights`, `level=campaign`, `time_increment=1`, `ads_read` | Onaylı **manuel** adım    | Resmî dokümanda `daily_budget` birimi belirtilmiyor; birimi doğrulanmamış bir değeri gerçek hesaba yazmıyoruz. |
| Google Ads                    | CSV/elle                                                                                                                  | Manuel                    | API, onaylı geliştirici jetonu + OAuth ister. Jeton verildiğinde bağlanır.                                     |
| Pinterest                     | CSV/elle                                                                                                                  | Manuel                    | API v5 erişimi uygulama onayı ister.                                                                           |
| TikTok                        | CSV/elle                                                                                                                  | Manuel                    | Onaylı geliştirici uygulaması gerekir.                                                                         |

## Kâr odaklı karar mantığı (Profit Engine üzerinde, deterministik)

- Son 90 günün **gerçek sipariş kârlılığından**: AOV ve reklam öncesi katkı.
- **Başa baş ROAS** = AOV ÷ reklam öncesi katkı. **Hedef ROAS** = AOV ÷ (reklam öncesi katkı − hedef katkı), varsayılan hedef 10 USD/sipariş.
  **Azami CPA** = reklam öncesi katkı − hedef katkı.
- Kampanya kararları: _veri yetersiz_ (tıklama < eşik ve harcama < 3×azami CPA), _zarar_, _hedef altı_, _hedefte_, _ölçeklenebilir_ (≥ 1,3 × hedef).
  Atıf güveni düşükse uyarı verilir. Kâr verisi yoksa karar verilmez.
- **Bütçe dağıtımı**: zarar edenlere 0 (durdur), verisi yetersizlere test payı (%20), kalanı ROAS ağırlıklı. Kuruşlar aşağı yuvarlanır; toplam
  **kullanıcının günlük sınırını asla aşmaz**. Sınırın üstündeki öneri API'de reddedilir.
- **Çift sayım yok**: `ad_spend` tek harcama defteridir. Her reklam hesabı harcamayı tek kaynaktan alır (`metrics` veya `ledger`). API ile
  raporlanan hesaba CSV yüklenemez. Defter kaynağına geçince eski CSV harcaması silinir. **Offsite Ads ücreti** sipariş başı ücrettir (Profit
  Engine) ve reklam harcaması olarak eşlenemez.

## Onay akışı

Öneri → onay isteği (`allocate_ad_budget` veya artışta `increase_ad_budget`): ne, neden, fayda, haftalık azami maliyet, kâr etkisi (başa baş/hedef
ROAS), API işlemi = **MANUEL**. Yeniden parola gerekir. Onaydan sonra durum **`awaiting_manual`** olur. Siz platform panelinde uygulayıp "Uyguladım"
deyince kampanya bütçeleri ve durumları kaydedilir ve denetim kaydına not düşülür. Uygulama onaysız hiçbir şeyi değiştirmez.

## Güvenlik

Meta jetonu yalnız sunucuda, AES-256-GCM ile şifreli (`oauth_tokens`) saklanır. Bağlanmadan önce hesap okunarak doğrulanır. Denetim kaydına ve
tarayıcıya jeton yazılmaz. Etsy defter kayıtlarını yalnız yöneticiler görür.

## Doğrulanmamış / dikkat

- Etsy defter `amount` alanı tamsayıdır, birimi belirtilmemiş. **Alt birim (cent)** varsayıldı (JPY gibi ondalıksız para birimleri olduğu gibi).
  `ledger_type` değerleri belgelenmemiş: sistem yalnız _öneri_ yapar ("Etsy Ads olabilir"), eşlemeyi siz seçersiniz.
- Meta satın alma eylem türleri için öncelik sırası: `omni_purchase` → `purchase` → `offsite_conversion.fb_pixel_purchase`. Bu adların hiçbiri resmî
  sayfada listelenmiyor. Eşleşme olmayan kampanyalar sonuçta raporlanır.
- Meta hız sınırı başlıkları doğrulanamadı. İstemci 613/80004/429/5xx hatalarında üstel bekleme ile en fazla 3 kez yeniden dener.

## Veritabanı

Migration `0019`: `ad_budget_policies`, `ad_budget_proposals`, `etsy_ledger_entries`, `store_settings.etsy_ads_ledger_types`,
`ad_accounts.spend_source/last_synced_at/last_error`, onay durumu `awaiting_manual` ve manuel onay alanları.

## Testler

Unit 149 · Integration 132 · E2E 17 — hepsi geçti. Meta Graph API ve Etsy (defter) sözleşme test sunucularıyla:

- jeton doğrulama ve şifreli saklama
- sayfalı içgörü aktarımı ve idempotent harcama
- CSV idempotensi
- başa baş/hedef ROAS ve kararlar
- sınır uygulaması
- onay → manuel uygulama
- defter eşlemesi ve Offsite Ads reddi

## Benden gerekenler

- İsteğe bağlı: Meta sistem kullanıcısı jetonu (`ads_read`) ve reklam hesabı kimliği. Panelden girilir, `.env`'e gerekmez.
- Etsy bağlantısı (`transactions_r`, zaten isteniyor).
- Google/Pinterest/TikTok API onayları alınırsa bağlantıları eklenebilir.
