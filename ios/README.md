# ios — iPhone Uygulaması (Aşama 13)

Henüz geliştirilmedi. Plan: Swift + SwiftUI, Keychain + Secure Enclave, APNs.

* iOS uygulaması işlem motoru değildir; kullanıcının masaüstündeki motorunun izleme ve
  uzaktan kumanda ekranıdır.
* Bağlantı bulut aktarma servisi üzerindendir. Komutlar Secure Enclave anahtarıyla imzalanır
  ve motor tarafından doğrulanır. Bulut tek başına emir veremez.
* Acil durdurma her zaman tek dokunuştur. Bot başlatma ve risk sınırı gevşetme gibi
  hassas komutlar Face ID ister.

Ayrıntılar: [`../docs/01-sistem-mimarisi.md`](../docs/01-sistem-mimarisi.md) §7.
