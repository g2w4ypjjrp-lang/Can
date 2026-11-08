import type { Metadata } from "next";

import { LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Gizlilik ve KVKK aydınlatma metni",
  description: "Hangi kişisel verileri, hangi amaçla işlediğimiz ve haklarınız (taslak).",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Gizlilik ve KVKK aydınlatma metni" updated="8 Kasım 2026">
      <p>
        Bu metin, 6698 sayılı Kişisel Verilerin Korunması Kanunu (“KVKK”) uyarınca veri sorumlusu sıfatıyla [Şirket
        unvanı] (“Şirket”, adres: [Adres]) tarafından, kişisel verilerinizin nasıl işlendiğini açıklamak için
        hazırlanmıştır.
      </p>

      <h2>1. Kısaca</h2>
      <ul>
        <li>
          Borsa API anahtarlarınız, işlem geçmişiniz, bakiyeleriniz ve strateji ayarlarınız <strong>yalnızca kendi
          bilgisayarınızda</strong> tutulur; bize gönderilmez.
        </li>
        <li>Bulutta yalnızca hesabınızı, lisanslarınızı ve güvenliği sağlamak için gereken veriler bulunur.</li>
        <li>Reklam veya analitik çerezi kullanmıyoruz; verilerinizi satmıyoruz.</li>
      </ul>

      <h2>2. İşlenen kişisel veriler</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Kategori</th>
            <th scope="col">Veriler</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Kimlik</td>
            <td>Ad soyad (isteğe bağlı)</td>
          </tr>
          <tr>
            <td>İletişim</td>
            <td>E-posta adresi</td>
          </tr>
          <tr>
            <td>Müşteri işlem</td>
            <td>Lisanslar, siparişler, fatura bilgileri, iletişim formu mesajları</td>
          </tr>
          <tr>
            <td>İşlem güvenliği</td>
            <td>IP adresi, tarayıcı/uygulama bilgisi, oturum kayıtları, giriş denemeleri, denetim kayıtları</td>
          </tr>
          <tr>
            <td>Cihaz</td>
            <td>
              Lisansın etkinleştirildiği cihazın adı ve platformu (Windows/iOS), cihaz kimliğinin geri döndürülemez özeti,
              bildirim için iPhone bildirim belirteci
            </td>
          </tr>
          <tr>
            <td>Pazarlama</td>
            <td>E-posta ile bilgilendirme izni (yalnızca açık rızanızla)</td>
          </tr>
        </tbody>
      </table>
      <p>
        Parolanız geri döndürülemez biçimde (Argon2id) özetlenerek saklanır; kimse, biz dâhil, parolanızı göremez. Ödeme
        kartı bilgileriniz tarafımızca saklanmaz; ödeme kuruluşu tarafından işlenir.
      </p>

      <h2>3. Amaçlar ve hukuki sebepler</h2>
      <ul>
        <li>
          Hesabın açılması, lisansın sağlanması ve cihaz etkinleştirme: sözleşmenin kurulması ve ifası (KVKK m. 5/2-c).
        </li>
        <li>Fatura ve muhasebe kayıtları: hukuki yükümlülüğün yerine getirilmesi (m. 5/2-ç).</li>
        <li>
          Hesap güvenliği, kötüye kullanımın ve dolandırıcılığın önlenmesi, denetim kayıtları: meşru menfaat (m. 5/2-f).
        </li>
        <li>Destek taleplerinin yanıtlanması: sözleşmenin ifası ve meşru menfaat.</li>
        <li>Kampanya ve yeni sürüm duyuruları: açık rıza (m. 5/1); izninizi her zaman geri alabilirsiniz.</li>
      </ul>

      <h2>4. iPhone ile uzaktan kontrol</h2>
      <p>
        Telefonunuz ile bilgisayarınız arasındaki mesajlar, aktarma servisimiz üzerinden TLS ile iletilir. Mesajlar
        cihazlarınızda imzalanır; servisimiz mesaj üretemez veya değiştiremez. Mesajlar özet durum bilgisi (motor
        durumu, pozisyon sembolleri, kâr/zarar özeti, uyarılar) içerir; API anahtarı ve hesap bakiyesi ayrıntısı
        içermez. Aktarma servisi mesajları saklamaz, yalnızca yönlendirir.
      </p>

      <h2>5. Çerezler</h2>
      <p>
        Yalnızca oturumunuzu sürdürmek için zorunlu olan bir çerez (<code>ati_session</code>) kullanılır. Bu çerez
        JavaScript tarafından okunamaz, yalnızca güvenli bağlantıda ve yalnızca hizmetimizin sunucusuna gönderilir. Analitik, reklam
        veya üçüncü taraf çerezi kullanılmaz; bu nedenle çerez onay penceresi gösterilmez.
      </p>

      <h2>6. Aktarım</h2>
      <p>Kişisel verileriniz, yukarıdaki amaçlarla sınırlı olarak aşağıdaki alıcılara aktarılabilir:</p>
      <ul>
        <li>Bulut altyapı sağlayıcısı: [Sağlayıcı, bölge]</li>
        <li>E-posta gönderim sağlayıcısı: [Sağlayıcı]</li>
        <li>Ödeme kuruluşu: [Sağlayıcı] (satın alma işlemleri için)</li>
        <li>Talep hâlinde yetkili kamu kurum ve kuruluşları</li>
      </ul>
      <p>
        Yurt dışında yerleşik bir sağlayıcı kullanılması hâlinde aktarım, KVKK m. 9'da öngörülen güvencelere uygun
        olarak yapılır.
      </p>

      <h2>7. Saklama süreleri (önerilen)</h2>
      <ul>
        <li>Hesap ve lisans verileri: hesap açık kaldığı sürece; kapanıştan sonra yasal zamanaşımı süresince.</li>
        <li>Fatura ve sipariş kayıtları: ilgili mevzuatta öngörülen süre boyunca (ör. 10 yıl).</li>
        <li>Oturum kayıtları: oturum bitiminden itibaren 30 gün.</li>
        <li>Denetim ve güvenlik kayıtları: [süre].</li>
        <li>İletişim formu mesajları: talebin kapanmasından itibaren 2 yıl.</li>
      </ul>
      <p>Süresi dolan veriler silinir, yok edilir veya anonim hâle getirilir.</p>

      <h2>8. Haklarınız (KVKK m. 11)</h2>
      <p>Şirket'e başvurarak;</p>
      <ul>
        <li>kişisel verilerinizin işlenip işlenmediğini öğrenme ve işlenmişse bilgi talep etme,</li>
        <li>işlenme amacını ve amacına uygun kullanılıp kullanılmadığını öğrenme,</li>
        <li>yurt içinde veya yurt dışında aktarıldığı üçüncü kişileri bilme,</li>
        <li>eksik veya yanlış işlenmişse düzeltilmesini, şartları oluşmuşsa silinmesini veya yok edilmesini isteme,</li>
        <li>bu işlemlerin aktarıldığı üçüncü kişilere bildirilmesini isteme,</li>
        <li>münhasıran otomatik sistemlerle analiz sonucu aleyhinize bir sonuç çıkmasına itiraz etme,</li>
        <li>kanuna aykırı işleme nedeniyle zarara uğramanız hâlinde zararın giderilmesini talep etme</li>
      </ul>
      <p>
        haklarına sahipsiniz. Başvurularınızı <a href="/iletisim">iletişim formunda</a> “Kişisel veriler (KVKK)”
        konusunu seçerek, [KEP adresi] üzerinden veya yazılı olarak [Adres] adresine iletebilirsiniz. Başvurular en geç
        30 gün içinde ücretsiz olarak sonuçlandırılır.
      </p>
    </LegalPage>
  );
}
