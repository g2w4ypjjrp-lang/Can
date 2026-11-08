import type { Metadata } from "next";

import { LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = { title: "Kullanım koşulları", description: "AI Trading Intelligence kullanım koşulları (taslak)." };

export default function TermsPage() {
  return (
    <LegalPage title="Kullanım koşulları" updated="8 Kasım 2026">
      <h2>1. Taraflar ve kapsam</h2>
      <p>
        Bu koşullar, [Şirket unvanı] (“Şirket”, adres: [Adres], MERSİS: [MERSİS no]) ile AI Trading Intelligence web
        sitesini (canarslan.net.tr), masaüstü uygulamasını ve iPhone uygulamasını (birlikte “Hizmet”) kullanan kişi (“Kullanıcı”)
        arasındaki ilişkiyi düzenler. Hesap oluşturan veya Hizmet'i kullanan Kullanıcı bu koşulları kabul etmiş sayılır.
      </p>

      <h2>2. Hizmetin tanımı</h2>
      <p>
        Hizmet; kripto varlık piyasa verilerini analiz eden, strateji testi, sanal işlem ve Kullanıcı'nın kendi borsa
        hesabında, kendi tanımladığı kurallarla otomatik işlem yapabilen bir yazılımdır. İşlem motoru Kullanıcı'nın
        bilgisayarında çalışır. Şirket, Kullanıcı adına borsa hesabı açmaz, varlık saklamaz, para transferi yapmaz ve
        yatırım danışmanlığı hizmeti vermez.
      </p>

      <h2>3. Hesap</h2>
      <ul>
        <li>Kullanıcı 18 yaşını doldurmuş ve fiil ehliyetine sahip olmalıdır.</li>
        <li>Hesap bilgileri doğru ve güncel tutulmalı, parola gizli saklanmalıdır.</li>
        <li>Hesapta gerçekleşen işlemlerden Kullanıcı sorumludur; yetkisiz kullanım fark edildiğinde Şirket'e bildirilmelidir.</li>
      </ul>

      <h2>4. Lisans</h2>
      <ul>
        <li>
          Satın alınan lisans; kişisel, devredilemez ve münhasır olmayan bir kullanım hakkı verir. Lisans, paketin
          süresi boyunca ve paketin izin verdiği bilgisayar sayısında kullanılabilir.
        </li>
        <li>Yazılımın kaynak koduna erişim, tersine mühendislik, lisans denetimini aşma ve yeniden satış yasaktır.</li>
        <li>Koşulların ihlali hâlinde Şirket lisansı askıya alabilir veya iptal edebilir.</li>
      </ul>

      <h2>5. Kullanıcının yükümlülükleri</h2>
      <ul>
        <li>Hizmet yalnızca Kullanıcı'nın kendi borsa hesabı ve kendi oluşturduğu API anahtarlarıyla kullanılabilir.</li>
        <li>Kullanıcı, borsanın kullanım koşullarına ve bulunduğu ülkenin mevzuatına uymakla yükümlüdür.</li>
        <li>Hizmet, piyasa manipülasyonu veya hukuka aykırı herhangi bir amaçla kullanılamaz.</li>
      </ul>

      <h2>6. Yatırım tavsiyesi değildir ve sorumluluğun sınırı</h2>
      <p>
        Hizmet'in ürettiği analizler yatırım tavsiyesi değildir ve Şirket hiçbir kazanç taahhüdünde bulunmaz.
        Kullanıcı'nın işlem kararları ve bunların sonuçları Kullanıcı'ya aittir. Şirket; piyasa hareketlerinden, borsa
        kesintilerinden, Kullanıcı'nın bilgisayarı veya internet bağlantısındaki sorunlardan ve Kullanıcı'nın
        ayarlarından doğan zararlardan, kasıt veya ağır ihmali bulunmadıkça sorumlu değildir. Ayrıntılar için risk
        bildirimine bakınız.
      </p>

      <h2>7. Hizmetin sürekliliği ve güncellemeler</h2>
      <p>
        Şirket Hizmet'i geliştirmek için güncellemeler yayımlayabilir. Bakım veya teknik zorunluluklar nedeniyle bulut
        hizmetlerinde (hesap, lisans doğrulama, telefon bağlantısı) geçici kesintiler olabilir.
      </p>

      <h2>8. Ücret, cayma ve iade</h2>
      <p>
        Paket ücretleri satın alma anında gösterilir. Ön bilgilendirme, cayma hakkı ve iade koşulları mesafeli satış
        sözleşmesinde düzenlenir ve satış öncesinde Kullanıcı'ya sunulur.
      </p>

      <h2>9. Fesih</h2>
      <p>
        Kullanıcı hesabını dilediği zaman kapatabilir. Şirket, bu koşulların esaslı ihlali hâlinde hesabı askıya
        alabilir veya kapatabilir.
      </p>

      <h2>10. Değişiklikler</h2>
      <p>Şirket bu koşulları güncelleyebilir. Esaslı değişiklikler yürürlükten önce e-posta veya site üzerinden duyurulur.</p>

      <h2>11. Uygulanacak hukuk ve yetki</h2>
      <p>
        Bu koşullara Türkiye Cumhuriyeti hukuku uygulanır. Uyuşmazlıklarda tüketici işlemleri bakımından mevzuatta
        belirlenen parasal sınırlar dâhilinde Tüketici Hakem Heyetleri ve Tüketici Mahkemeleri; diğer hâllerde [Şehir]
        mahkemeleri ve icra daireleri yetkilidir.
      </p>

      <h2>12. İletişim</h2>
      <p>
        Sorularınız için <a href="/iletisim">iletişim formunu</a> veya [KEP adresi] adresini kullanabilirsiniz.
      </p>
    </LegalPage>
  );
}
