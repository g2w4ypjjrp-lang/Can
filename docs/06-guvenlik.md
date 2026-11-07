# 06 — Güvenlik Tasarımı

## 1. Korunan varlıklar ve tehditler

| Varlık | Tehdit | Önlem | Durum |
|---|---|---|---|
| Binance API anahtarı | Diskten çalınma, loglara sızma, buluta gönderilme | DPAPI ile kullanıcıya bağlı şifreleme; kayıt adına bağlı ek doğrulanmış veri (AAD); log maskeleme; anahtar asla bilgisayardan çıkmaz | ✅ Aşama 1 |
| Kullanıcı fonları | Para çekme yetkili anahtarın kötüye kullanımı | Para çekme / iç transfer / evrensel transfer yetkisi açık anahtar **reddedilir**; IP kısıtı yoksa uyarı | ✅ Politika (Aşama 1), uç nokta çağrısı Aşama 10 |
| Kullanıcı fonları | Hatalı/istem dışı gerçek işlem | Varsayılan PAPER; LIVE için ayar + onay ifadesi + tüm kontroller; Aşama 1'de LIVE imkânsız; kalıcı acil durdurma | ✅ |
| Kullanıcı fonları | Bilgisayar/internet kesintisinde sahipsiz pozisyon | Borsa tarafı koruyucu stop emirleri; güvenli mod; açılışta mutabakat | 🔜 Aşama 10-11 |
| Yerel kontrol API'si | Aynı makinedeki kötü niyetli web sitesi (DNS rebinding / CSRF), yerel ağdan erişim | Yalnızca loopback; Bearer belirteç (sabit zamanlı karşılaştırma); `Host` başlığı denetimi; WebSocket'te `Origin` denetimi ve ilk mesajda kimlik doğrulama; Windows'ta `SO_EXCLUSIVEADDRUSE` | ✅ |
| Yerel durum | Aynı hesapta iki motorun çift emir göndermesi | İşletim sistemi düzeyinde tek örnek kilidi | ✅ |
| Denetim kaydı | Sessizce değiştirme/silme | Yerel: SQLite tetikleyicileri + SHA-256 hash zinciri (`verify-audit`). Bulut: tetikleyiciler + `audit_log_verify()`; süper kullanıcı tetikleyiciyi kapatsa bile değişiklik tespit edilir | ✅ |
| Müşteri parolaları | Veritabanı sızıntısı | Yalnızca Argon2id (şemada zorunlu) | ✅ şema / 🔜 Aşama 15 |
| Lisans anahtarları | Sızıntı, tahmin, ikinci satış | HMAC-SHA256 + pepper ile arama özeti; KMS zarf şifreleme; 75 bit rastgelelik; hız sınırlama; durum makinesi ve tek seferlik tahsis veritabanında zorunlu | ✅ şema / 🔜 Aşama 15 |
| Yönetici paneli | Hesap ele geçirme, yetki aşımı | Ayrı tablo/oturum; 2FA olmadan aktif olamaz (şema kısıtı); oturum ≤ 12 saat; RBAC (`admin_effective_permissions`); hassas işlemler (anahtar görme, iade) ayrı yetki; tüm işlemler denetim kaydında | ✅ şema / 🔜 Aşama 16 |
| Ödemeler | Sahte veya tekrar gönderilen webhook | İmza doğrulanmadan işlenemez (şema kısıtı); olay kimliği tekil; sipariş başına tek başarılı ödeme; birim başına tek lisans | ✅ şema / 🔜 Aşama 17 |
| iOS uzaktan komutları | Bulutun veya ağın ele geçirilmesi, tekrar oynatma | Secure Enclave anahtarıyla imza; motorda doğrulama; zaman damgası + sayaç; komut izin listesi; hassas komutlarda Face ID | 🔜 Aşama 13 |
| Bulut veritabanı bağlantısı | Ortadaki adam saldırısı | Staging/production'da `sslmode=verify-full` zorunlu (ayar doğrulaması) | ✅ |
| Tedarik zinciri | Kötü niyetli bağımlılık | Kilit dosyaları (`uv.lock`), CI'da `--locked`, bağımlılık taraması (Aşama 18), kod imzalama | ✅ kısmen |

## 2. Gizli bilgi yönetimi

| Gizli bilgi | Nerede saklanır |
|---|---|
| Binance API anahtarı/gizli anahtarı | Kullanıcı bilgisayarı, `secrets` tablosu, DPAPI ile şifreli |
| Yerel API belirteci | Masaüstü kabuğu üretir, ortam değişkeniyle iletir (diske yazılmaz). Bağımsız çalıştırmada `runtime/local-api.json` (yalnızca kullanıcı okuyabilir) |
| Lisans kirası (lease) | Kullanıcı bilgisayarı, `secrets` tablosu |
| iOS cihaz anahtarı | Secure Enclave (çıkarılamaz) |
| Bulut: DB parolası, lisans pepper'ı, ödeme sağlayıcı anahtarları, kira imzalama anahtarı | Yönetilen gizli bilgi deposu (KMS destekli); depoda veya imajda asla bulunmaz |

## 3. Binance API anahtarı kullanım kuralları

1. Kullanıcıya anahtar oluştururken **yalnızca** "Okuma" + gerekli işlem yetkisi
   (Spot ve/veya Futures) açması söylenir. **Para çekme kesinlikle kapalı.**
2. Mümkünse IP kısıtı (yalnızca kullanıcının bilgisayarının dış IP'si).
3. Motor, anahtar kaydedilir kaydedilmez ve her açılışta yetkileri doğrular
   (`evaluate_api_restrictions`); kural ihlalinde anahtar kullanılmaz ve kullanıcıya
   nedeni gösterilir.
4. Bilinmeyen/eksik yetki alanları **güvensiz** kabul edilir.

## 4. Log ve hata mesajı hijyeni

* Anahtar adına göre maskeleme: `api_key`, `secret`, `signature`, `token`, `password`,
  `authorization`, `listenKey`, `cookie`, `session`, `totp` ...
* Değer biçimine göre maskeleme: 48+ karakterlik alfasayısal dizgiler (API anahtarı/imza
  biçimi), URL'deki `signature=` / `listenKey=` / `apiKey=` parametreleri, `Bearer` belirteçleri.
* Denetim kaydı ayrıntıları da yazılmadan önce maskelenir.
* Test: `test_redact_by_key_name`, `test_redact_by_value_shape`, duman testinde log
  dosyasında belirteç bulunmadığının kontrolü.

## 5. Kişisel veriler (KVKK / GDPR)

* Bulutta yalnızca hesap, lisans, cihaz ve ödeme için gereken minimum veri tutulur; işlem
  verisi ve API anahtarları buluta gönderilmez.
* Cihaz parmak izi ham değil, SHA-256 özeti olarak saklanır.
* Hesap silme: `customers.status = 'deleted'` + kişisel alanların anonimleştirilmesi; yasal
  saklama yükümlülüğü olan fatura kayıtları ayrı tutulur.
* Veri bölgesi ve yurt dışı aktarım kararı açık kararlar listesindedir (`05`).
