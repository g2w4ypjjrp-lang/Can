# Lisans protokolü v1 (motor ↔ bulut lisans servisi)

Kullanıcının bilgisayarındaki motor, lisansını buluttaki hesap/lisans API'sinden
(`https://api.canarslan.net.tr`) **imzalı ve cihaza bağlı bir kira** (lease) alarak doğrular.
Kira çevrim dışı doğrulanabilir. Motor kirayı düzenli yeniler; internet yokken kira
belirli bir süre daha geçerli kalır.

Kod: bulut `cloud/src/ati_cloud/licensing/`, motor `engine/src/ati_engine/licensing/`.
Test vektörleri: [`test-vectors/license-v1.json`](test-vectors/license-v1.json). Bulut üretir,
motor doğrular.

## Lisans anahtarı

```text
ATI-XXXX-XXXX-XXXX-XXXX        örnek: ATI-7XK9-PQ82-MN45-ZR61
```

- 16 karakter, Crockford Base32 alfabesi: `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (`I L O U` yok).
- İlk 15 karakter kriptografik rastgeledir (2⁷⁵ olasılık).
- 16. karakter **Luhn mod 32** kontrol karakteridir. Tüm tek karakter hatalarını ve yan yana
  yer değiştirmelerin büyük çoğunluğunu sunucuya gitmeden yakalar.
- Okurken: büyük/küçük harf, boşluk ve tire önemsizdir; `O→0`, `I/L→1` düzeltilir.
- Bulutta anahtarın kendisi aranmaz:
  - arama `HMAC-SHA256(pepper, anahtar)` ile yapılır;
  - müşteri panelinde yeniden gösterim için AES-256-GCM zarf şifrelemesiyle saklanır
    (satıra bağlı AAD);
  - listelerde yalnızca ipucu (`ATI-****-****-****-ZR61`) kullanılır.
- Motor anahtarı **saklamaz**; yalnızca ipucunu saklar.

## Cihaz kimliği

| Öğe | Değer |
|---|---|
| Parmak izi | `SHA-256("ati-device-v1|" + makine kimliği)`. Windows'ta `MachineGuid`. Makine kimliğinin kendisi gönderilmez. Aynı bilgisayara yeniden kurulumda değişmez. |
| Cihaz anahtarı | Ed25519, motorun şifreli kasasında (DPAPI). Her istek bununla imzalanır. |

## İmzalı mesaj

Uzaktan kontrol protokolüyle aynı biçim: `{"p": "<JSON metni>", "s": "<base64 imza>"}`. İmza
`p` metninin UTF-8 baytları üzerine atılır. `p` içinde her zaman şu alanlar bulunur:

- `v` (sürüm, 1)
- `type`
- `ts_ms` (sunucu saatine göre; motor sunucudan öğrendiği saat farkını kullanır)
- `nonce`

### Motor → bulut

| Uç nokta | `type` | `p` içindeki ek alanlar | İmza anahtarı |
|---|---|---|---|
| `POST /v1/licenses/activate` | `activate` | `license_key`, `device_key` (b64), `fingerprint` (hex), `name`, `platform`, `app_version`, `os_version` | İstekteki `device_key`. Anahtara sahip olunduğunu kanıtlar. |
| `POST /v1/licenses/renew` | `renew` | `license_id`, `device_id` | Kayıtlı cihaz anahtarı |
| `POST /v1/licenses/deactivate` | `deactivate` | `license_id`, `device_id` | Kayıtlı cihaz anahtarı |

Sunucunun denetim sırası:

1. biçim ve sürüm;
2. **imza**;
3. saat farkı ≤ 300 sn (`stale`);
4. yenileme ve bırakma isteklerinde `ts_ms` > aktivasyonun son isteği (`replay`);
5. lisans durumu.

İmza tekrar oynatma kaydından **önce** denetlenir; sahte istek sayacı ilerletemez.

Aktivasyon kuralları:

- Aynı müşteri ve aynı parmak izi = aynı bilgisayar.
- Yeniden kurulumda cihaz anahtarı yenilenir. Eski kurulumun yenileme istekleri bundan sonra
  `bad_signature` alır.
- Bilgisayar sınırı veritabanı tetikleyicisiyle zorlanır. Eşzamanlı isteklerde bile aşılamaz.
- Lisans süresi ilk aktivasyonla başlar (`sold → active`).

### Bulut → motor (kira)

```json
{"lease": {"p": "...", "s": "..."}, "server_time_ms": 1800000000000}
```

`p` içeriği:

| Alan | Açıklama |
|---|---|
| `type` | `license_lease` |
| `kid` | İmza anahtarı kimliği: `SHA-256(açık anahtar)` ilk 16 onaltılık karakter. Motor yalnızca gömülü güvenilir anahtarları (`license.trusted_keys`) kabul eder. |
| `license_id`, `serial`, `plan_code`, `plan_name`, `status` | Lisans |
| `license_expires_at` | Lisans bitişi (ms) veya `null` (süresiz) |
| `device_limit`, `companion_device_limit` | Bilgisayar ve telefon sınırı |
| `device_id`, `device_key`, `fingerprint` | Kiranın bağlı olduğu cihaz. Motor kendi anahtarı ve parmak iziyle karşılaştırır. |
| `issued_at` | Veriliş zamanı |
| `valid_until` | Veriliş + 24 saat. Lisans bitişine kırpılır. |
| `offline_until` | Veriliş + 72 saat. Sunucuya ulaşılamazsa sınır budur. |

## Motor durumları

| Durum | Anlamı | Yeni işlem (zorunlu kipte) |
|---|---|---|
| `active` | Kira geçerli | Açılabilir |
| `offline_grace` | Yenilenemedi, `offline_until` öncesi | Açılabilir |
| `lease_expired` | Çevrim dışı tolerans doldu | Açılamaz |
| `license_expired` | Lisans süresi bitti | Açılamaz |
| `revoked` | Sunucu kalıcı reddetti: `not_found`, `cancelled`, `frozen`, `expired`, `not_activated`, `device_revoked`, `bad_signature` | Açılamaz |
| `clock_error` | Saat, görülen en ileri zamandan 10 dakikadan fazla geri | Açılamaz |
| `unlicensed` / `not_configured` | Lisans yok / bu sürümde güvenilir anahtar yok | Açılamaz / zorunluluk kapalı |

Ek kurallar:

- Açık pozisyonlar ve stoplar her durumda yönetilmeye devam eder.
- Ağ hatası, 429, 5xx, `stale` ve `replay` geçicidir; kira korunur.
- Yenileme etkin durumda 6 saatte bir, sorun varken 5 dakikada bir yapılır.

Zorunluluk (`license.enforce`) açıkken `license.valid` hazırlık koşulu geçerli durumlar dışında
yanlıştır. Bu durumda motor güvenli moda iner. Telefon eşleştirmesinde kiradaki
`companion_device_limit` uygulanır (bkz. `remote-v1.md`, `device_limit`).

## Müşteri paneli (çerezli, köken denetimli)

| Uç nokta | Açıklama |
|---|---|
| `GET /v1/me` | Her lisans için `devices` (etkin bilgisayarlar) ve `device_resets_left` |
| `POST /v1/me/licenses/{id}/devices/{device_id}/deactivate` | Bilgisayar kaldırma. 30 günde en fazla 3 (`reset_limit`). |
| `POST /v1/me/licenses/{id}/reveal` | Tam anahtar. Parola yeniden istenir, `Cache-Control: no-store`, denetim kaydı, hız sınırı. |

## Hata biçimi

```json
{"detail": {"code": "device_limit", "message": "Bu lisans için bilgisayar sınırına ulaşıldı. ..."}}
```

Kodlar:

- `invalid_key`, `not_found`, `frozen`, `cancelled`, `expired`;
- `device_limit`, `device_revoked`, `not_activated`;
- `bad_signature`, `stale`, `replay`, `malformed`;
- `reset_limit`, `unavailable` (lisans servisi yapılandırılmamış).
