# ios — iPhone uygulaması (Aşama 13)

SwiftUI, iOS 17+. Telefon, bilgisayardaki işlem motoruna buluttaki aktarma servisi üzerinden
bağlanır. Her komut telefonun Secure Enclave anahtarıyla imzalanır; motor imzayı doğrulamadan
hiçbir komutu uygulamaz. Protokol: [`../shared/protocol/remote-v1.md`](../shared/protocol/remote-v1.md).

## Yapı

- `ATICore/`: platformdan bağımsız Swift paketi.
  - Protokol, P-256/Ed25519 imza ve doğrulama.
  - Eşleştirme kodu doğrulama, sıra numarası, oturum denetleyicisi (`RemoteController`).
  - Motor benzetimi (`MockEngine`).
  - Linux'ta (swift-crypto) ve macOS'ta (CryptoKit) test edilir: `cd ATICore && swift test`.
- `App/`: SwiftUI ekranları, Secure Enclave anahtarları (Face ID korumalı ikinci anahtar),
  WebSocket bağlantısı, QR okuyucu, yerel bildirimler.
- `AppUITests/`: XCUITest senaryoları. Uygulama `-UITestMockEngine` ile bellek içi motorla
  açılır.
- `project.yml`: XcodeGen tanımı.

## Geliştirme (macOS)

```bash
brew install xcodegen
xcodegen generate
open ATI.xcodeproj
xcodebuild test -project ATI.xcodeproj -scheme ATI -destination 'platform=iOS Simulator,name=iPhone 16' CODE_SIGNING_ALLOWED=NO
```

## Bekleyenler

- Cihaza kurulum, TestFlight ve App Store: Apple Developer hesabı (**G6**).
- Uygulama kapalıyken anlık bildirim (APNs): bulut dağıtımı (**G5**) ve Apple hesabı.
- Hesap girişi ve lisans ekranı: bulut hesap API'si (Aşama 15).
