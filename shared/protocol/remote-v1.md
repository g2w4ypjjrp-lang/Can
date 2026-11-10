# Uzaktan kontrol protokolü v1 (iOS ↔ aktarma ↔ motor)

Telefon ile kullanıcının bilgisayarındaki işlem motoru arasında, buluttaki **aktarma
servisi** üzerinden çalışan, uçtan uca **imzalı ve şifreli** mesajlaşma. Aktarma servisi
mesajları yalnızca yönlendirir. Hiçbir anahtarı yoktur. **Bulut ele geçirilse bile komut
üretemez, motorun durumunu sahteleyemez, cihaz eşleştiremez ve mesaj içeriklerini okuyamaz.**

## Anahtarlar

| Taraf | Anahtar | Saklandığı yer | Kimlik |
|---|---|---|---|
| Motor | Ed25519 | Motorun şifreli kasası (DPAPI) | `engine_id` = SHA-256(açık anahtar ham 32 bayt) ilk 16 bayt, onaltılık |
| Telefon | P-256 **imza anahtarı** (`signing`) | Secure Enclave (yoksa Anahtar Zinciri) | `device_id` = SHA-256(X9.63 açık anahtar) ilk 16 bayt, onaltılık |
| Telefon | P-256 **korumalı anahtar** (`guarded`) | Secure Enclave, **Face ID/Touch ID zorunlu** erişim denetimiyle | — |
| Motor | P-256 **şifreleme anahtarı** (`engine_kx`) | Motorun şifreli kasası | — |
| Telefon | P-256 **şifreleme anahtarı** (`kx_key`) | Secure Enclave (anahtar anlaşması) | — |

Korumalı anahtar Face ID olmadan imza atamaz. Bu yüzden korumalı anahtarla imzalanmış komut,
telefonda biyometrik doğrulama yapıldığının kanıtıdır. Kanıt telefonun beyanına değil,
donanıma dayanır.

## İmzalı mesaj biçimi

İmza, **gönderilen metnin kendisi** üzerine atılır. Taraflar arası JSON kanonikleştirme
sorunu böylece ortadan kalkar:

```json
{"p": "<JSON metni>", "s": "<imza, base64>"}
```

- Telefon → motor: P-256 ECDSA/SHA-256. İmza ham `r‖s` biçimindedir (64 bayt).
- Motor → telefon: Ed25519 (64 bayt).

Alıcı önce imzayı `p` metninin UTF-8 baytları üzerinde doğrular, sonra `p`'yi ayrıştırır.

## Eşleştirme

1. Masaüstü QR kod gösterir. İçeriği:

   ```json
   {"v":1,"relay":"wss://…","engine_id":"…","engine_key":"<b64>","engine_kx":"<b64 X9.63>",
    "pair":"<b64url gizli>","exp":<ms>}
   ```

   - `engine_kx`: motorun şifreleme anahtarı. QR bant dışı olduğundan güvenilir kaynaktır;
     eşleştirme isteği de bu anahtara şifrelenir.

   - `pair` 32 baytlık tek kullanımlık gizli değerdir; 5 dakika geçerlidir.
   - Bu değer yalnızca kamera ile (bant dışı) aktarılır. Aktarma servisi görmez.
2. Telefon anahtarlarını üretir ve aktarma servisine bağlanır. Motora `pair_request`
   gönderir.
   - `p` içeriği: `type`, `engine_id`, `device_id`, `name`, `signing_key`, `guarded_key`,
     `kx_key` (telefonun şifreleme anahtarı, X9.63), `protection` (`secure_enclave` |
     `software`), `ts_ms`, `nonce`.
   - Kanıt: `proof` = base64(HMAC-SHA256(pair, p)).
   - İmza: `s`, imza anahtarıyla atılır (anahtara sahip olduğunu kanıtlar).
3. Motor şunları denetler:
   - etkin oturum var mı ve süresi doldu mu;
   - HMAC kanıtı (sabit zamanlı karşılaştırma);
   - imza;
   - `device_id` türetimi.

   Hepsi geçerse cihazı kaydeder, oturumu siler ve imzalı `pair_result` döner.

   Gizli değeri bilmeyen aktarma servisi geçerli kanıt üretemez. Aynı istek tekrar
   gönderilirse oturum bittiği için reddedilir.

   Başarısız eşleştirmeye yanıt verilmez. Tek istisna `device_limit`'tir (Aşama 15): lisans
   zorunluyken kiradaki telefon sınırı doluysa reddedilir. Kanıt ve imza doğrulandıktan sonra
   oluştuğu için imzalı `pair_result` (`ok: false`, `reason: device_limit`) gönderilir.

## Komutlar (telefon → motor)

`p` içeriği:

```json
{"v":1,"type":"command","engine_id":"…","device_id":"…","key":"signing|guarded",
 "seq":1794100000123,"ts_ms":1794100000123,"command":"engage_kill_switch","args":{}}
```

Motorun denetim sırası. İlk başarısız adımda komut **reddedilir** ve kayda geçer:

| # | Denetim | Ret nedeni |
|---|---|---|
| 1 | Biçim, `v`, `type` | `malformed` |
| 2 | `engine_id` bu motor mu | `wrong_engine` |
| 3 | Cihaz kayıtlı ve iptal edilmemiş mi | `unknown_device`, `revoked_device` |
| 4 | İmza, belirtilen anahtarla geçerli mi | `bad_signature` |
| 5 | Zaman farkı ≤ 120 sn | `stale` |
| 6 | `seq` > cihazın son kabul edilen `seq`'i (kalıcı) | `replay` |
| 7 | Komut izin listesinde mi | `not_allowed` |
| 8 | Komut korumalı anahtar istiyor mu | `biometric_required` |

İmza, sıra numarasından **önce** denetlenir. Saldırgan sahte mesajla sıra numarasını
ilerletemez.

Telefon `seq` değerini `max(son_seq + 1, şimdi_ms)` olarak üretir. Uygulama yeniden kurulsa da
sayı geriye gitmez.

### İzin listesi

| Komut | Anahtar | Etki |
|---|---|---|
| `engage_kill_switch` | signing | Acil durdurma (her zaman tek dokunuş) |
| `pause_autotrade` | signing | Otomatik işlemi durdurur |
| `request_snapshot` | signing | Güncel durum ister |
| `resume_autotrade` | guarded | Otomatik işlemi başlatır |
| `release_kill_switch` | guarded | Acil durdurmayı kaldırır |
| `close_position` | guarded | `{market, symbol}` pozisyonunu kapatır |
| `close_all` | guarded | Tüm pozisyonları kapatır |

Uzaktan **asla** yapılamayanlar: para çekme, yeni pozisyon açma, risk sınırlarını
değiştirme, API anahtarı girme, işlem modunu değiştirme (özellikle gerçek hesap).

## Motor → telefon

Tüm mesajlar Ed25519 ile imzalanır. Telefon, QR'dan aldığı `engine_key` ile doğrular. `p`
türleri:

- `pair_result`
- `result`: komut sonucu (`seq`, `ok`, `reason`, `message`)
- `snapshot`: özet durum (motor, risk, pozisyonlar, fırsatlar, balina uyarıları)
- `event`: bildirim (balina uyarısı, işlem açıldı/kapandı, acil durdurma, risk olayı)

Bildirim içerikleri yalnızca özettir. API anahtarı, emir kimliği veya hesap bakiyesi
ayrıntısı içermez.

## Aktarma servisi

- Motor `/v1/relay/engine` adresine bağlanır. İlk mesaj `hello`'dur:
  - içerik: `engine_id`, `key`, `ts_ms`;
  - imza: Ed25519, `ati-relay-hello|engine|<engine_id>|<ts_ms>` metni üzerine.
- Telefon `/v1/relay/device` adresine bağlanır:
  - içerik: `device_id`, `engine_id`, `key` (imza anahtarı), `ts_ms`;
  - imza: P-256, `ati-relay-hello|device|<device_id>|<engine_id>|<ts_ms>` metni üzerine.

Aktarma servisi kimlik türetimini ve imzayı denetler. Böylece başkasının kimliğiyle
bağlanılamaz; yönlendirme ve hizmet dışı bırakma saldırılarına karşı korur. Eşleştirmeyi
denetlemez; bunu motor yapar.

Yönlendirme:

- `{"type":"to_engine","msg":…}` → motora `{"type":"from_device","device_id":…,"msg":…}`
- `{"type":"to_device","device_id":"…","msg":…}` → yalnızca o telefona
  `{"type":"from_engine","msg":…}`. Yayın yoktur: aynı kanala bağlanmış ama eşleştirilmemiş bir
  cihaz motor mesajlarını göremez.
- Durum bildirimleri: `device_online`, `device_offline`, `engine_offline`

Bağlantı başına hız sınırı uygulanır. Motor başına en fazla 20 telefon bağlanabilir.

Test vektörleri: [`test-vectors/remote-v1.json`](test-vectors/remote-v1.json).

## Uçtan uca şifreleme (Aşama 18)

Aktarma çerçevelerindeki `msg`, imzalı mesajın (`{"p","s"[,"proof"]}`, boşluksuz JSON) alıcının
şifreleme anahtarına şifrelenmiş hâlidir. Önce imzalanır, sonra şifrelenir; alıcı önce çözer,
sonra imzayı (yukarıdaki kurallarla) doğrular.

```json
{"v":1,"e":"<geçici açık anahtar, X9.63, b64>","n":"<12 bayt nonce, b64>","c":"<şifreli metin ‖ 16 bayt etiket, b64>"}
```

1. Gönderen her mesaj için yeni bir geçici P-256 anahtarı üretir.
2. `ortak = ECDH(geçici, alıcı)` (x koordinatı, 32 bayt).
3. `anahtar = HKDF-SHA256(ikm=ortak, salt=geçici_açık ‖ alıcı_açık, info, 32 bayt)`.
4. `c = AES-256-GCM(anahtar, n, düz_metin, ek_veri=info)`.

`info = "ati-remote-v1|<yön>|<engine_id>|<device_id>"`; yön motor → telefon için `e2d`,
telefon → motor için `d2e`. Bağlam hem anahtar türetiminde hem GCM ek verisindedir. Aktarma
servisi bir mesajı başka cihaza ya da ters yöne yönlendirirse mesaj çözülemez.

Neden X25519 değil de P-256: telefonun şifreleme anahtarı Secure Enclave'de üretilir ve cihazdan
çıkmaz. Secure Enclave anahtar anlaşmasında yalnızca P-256'yı destekler.

Kurallar:

- Şifresiz, çözülemeyen veya değiştirilmiş mesaj işlenmez ve yanıtlanmaz. Motor bunu
  `undecryptable` olarak kaydeder; telefon reddedilen çerçeve sayacını artırır.
- Şifreleme anahtarı olmadan (bu sürümden önce) eşleşmiş cihaza mesaj gönderilmez; yeniden
  eşleştirme gerekir. `engine_kx` içermeyen QR kodu telefon tarafından reddedilir.
- Telefonun şifreleme anahtarı açık olduğundan saldırgan da ona şifreli zarf üretebilir.
  Gerçeklik zarfın değil, içindeki imzanın sorumluluğundadır. Şifreleme gizlilik sağlar,
  imza kimlik doğrular.

Test vektörleri (`envelope`): her iki yön için sabit anahtarlar, geçici anahtar ve nonce ile
üretilmiş zarflar. Python ve Swift aynı baytları üretir ve birbirinin zarfını çözer.

## Gizlilik notu

Aktarma servisi yalnızca yönlendirme bilgisini görür: `engine_id`, `device_id`, bağlantı
zamanları ve şifreli zarfların boyutu. Özet, komut, bildirim ve eşleştirme içerikleri uçtan uca
şifrelidir. API anahtarı, emir kimliği ve hesap ayrıntısı zaten hiç gönderilmez.
