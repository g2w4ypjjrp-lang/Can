import type { Metadata } from "next";

import { LegalPage } from "@/components/LegalPage";
import { SellerBlock } from "@/components/SellerBlock";
import { TextLink } from "@/components/ui";
import { fetchSeller } from "@/lib/seller";

export const metadata: Metadata = {
  title: "Ön bilgilendirme formu",
  description: "Mesafeli satış öncesi ön bilgilendirme formu (taslak).",
};

export default async function PreInformationPage() {
  const seller = await fetchSeller();
  return (
    <LegalPage title="Ön bilgilendirme formu" updated="9 Kasım 2026">
      <p>
        Bu form, 6502 sayılı Tüketicinin Korunması Hakkında Kanun ve Mesafeli Sözleşmeler Yönetmeliği uyarınca, mesafeli
        satış sözleşmesi kurulmadan önce alıcıyı bilgilendirmek amacıyla hazırlanmıştır.
      </p>

      <h2>1. Satıcı</h2>
      <SellerBlock seller={seller} />

      <h2>2. Ürünün temel nitelikleri</h2>
      <p>
        Ürün, AI Trading Intelligence yazılımının seçilen paket süresi ve bilgisayar sayısı için kullanım lisansıdır
        (dijital içerik). Lisans; masaüstü uygulamasını, iPhone uygulamasını ve paketin kapsadığı özellikleri içerir.
        Paket adı, süresi, bilgisayar sayısı ve toplam bedel ödeme sayfasındaki sipariş özetinde gösterilir.
      </p>
      <p>
        Yazılım bir analiz ve işlem otomasyonu aracıdır; yatırım danışmanlığı değildir ve hiçbir kazanç garantisi
        vermez. Kripto varlık işlemleri sermaye kaybı riski taşır (bkz.{" "}
        <TextLink href="/yasal/risk-bildirimi">risk bildirimi</TextLink>).
      </p>

      <h2>3. Fiyat ve ödeme</h2>
      <ul>
        <li>Ödeme sayfasında gösterilen tutar, vergiler dahil toplam satış bedelidir.</li>
        <li>
          Ödeme, lisanslı ödeme kuruluşunun güvenli ödeme sayfasında banka veya kredi kartıyla yapılır. Kart bilgileri
          Satıcı tarafından görülmez ve saklanmaz.
        </li>
        <li>Ek teslimat ücreti yoktur.</li>
      </ul>

      <h2>4. Teslimat</h2>
      <p>
        Lisans, ödemenin ödeme kuruluşu tarafından onaylanmasının hemen ardından alıcının hesabına elektronik ortamda
        tanımlanır ve müşteri panelinde görüntülenir; ayrıca e-posta ile bilgilendirme yapılır. Lisans süresi, lisansın
        ilk bilgisayarda etkinleştirildiği anda başlar.
      </p>

      <h2>5. Cayma hakkı</h2>
      <p>
        Mesafeli Sözleşmeler Yönetmeliği’nin 15. maddesinin birinci fıkrasının (ğ) bendi uyarınca, elektronik ortamda
        anında ifa edilen hizmetler ile tüketiciye anında teslim edilen gayrimaddi mallara ilişkin sözleşmelerde cayma
        hakkı kullanılamaz. Alıcı, ödeme öncesinde lisansın anında teslim edileceğini ve bu nedenle cayma hakkının
        bulunmadığını onaylar. Ayıplı ifa ve iade koşulları için{" "}
        <TextLink href="/yasal/iptal-ve-iade">cayma, iptal ve iade koşullarına</TextLink> bakınız.
      </p>

      <h2>6. Sözleşmenin süresi</h2>
      <p>
        Sözleşme, satın alınan paketin süresi boyunca (süresiz paketlerde lisans iptal edilene kadar) geçerlidir. Paket
        süresi sonunda lisans kendiliğinden yenilenmez ve otomatik ödeme alınmaz.
      </p>

      <h2>7. Şikâyet ve itiraz</h2>
      <p>
        Talep ve şikâyetler yukarıdaki iletişim bilgilerine veya <TextLink href="/iletisim">iletişim formuna</TextLink>{" "}
        iletilebilir. Uyuşmazlıklarda, Ticaret Bakanlığınca her yıl belirlenen parasal sınırlar dahilinde alıcının veya
        satıcının yerleşim yerindeki tüketici hakem heyetlerine, bu sınırları aşan durumlarda tüketici mahkemelerine
        başvurulabilir.
      </p>

      <h2>8. Kişisel veriler</h2>
      <p>
        Sipariş sırasında alınan kişisel veriler <TextLink href="/yasal/gizlilik">gizlilik ve KVKK aydınlatma
        metninde</TextLink> belirtilen amaçlarla işlenir.
      </p>
    </LegalPage>
  );
}
