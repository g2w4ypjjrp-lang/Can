import type { Metadata } from "next";

import { LegalPage } from "@/components/LegalPage";
import { SellerBlock } from "@/components/SellerBlock";
import { TextLink } from "@/components/ui";
import { fetchSeller } from "@/lib/seller";

export const metadata: Metadata = {
  title: "Mesafeli satış sözleşmesi",
  description: "Lisans satışına ilişkin mesafeli satış sözleşmesi (taslak).",
};

export default async function DistanceSalesPage() {
  const seller = await fetchSeller();
  return (
    <LegalPage title="Mesafeli satış sözleşmesi" updated="9 Kasım 2026">
      <h2>Madde 1 — Taraflar</h2>
      <p>
        <strong>Satıcı:</strong>
      </p>
      <SellerBlock seller={seller} />
      <p>
        <strong>Alıcı:</strong> Sipariş sırasında bilgilerini giren ve ödeme sayfasındaki onay kutularını işaretleyerek
        siparişi veren gerçek veya tüzel kişi. Alıcının ad, adres, telefon ve e-posta bilgileri siparişte kayıtlıdır.
      </p>

      <h2>Madde 2 — Konu</h2>
      <p>
        Bu sözleşmenin konusu, Alıcının canarslan.net.tr üzerinden elektronik ortamda siparişini verdiği AI Trading
        Intelligence yazılım kullanım lisansının satışı ve teslimine ilişkin olarak tarafların 6502 sayılı Tüketicinin
        Korunması Hakkında Kanun ve Mesafeli Sözleşmeler Yönetmeliği hükümleri uyarınca hak ve yükümlülüklerinin
        belirlenmesidir.
      </p>

      <h2>Madde 3 — Ürün, bedel ve ödeme</h2>
      <ul>
        <li>Ürünün paket adı, süresi, bilgisayar sayısı ve vergiler dahil toplam bedeli sipariş özetinde yer alır ve bu sözleşmenin parçasıdır.</li>
        <li>Ödeme, lisanslı ödeme kuruluşu aracılığıyla peşin olarak yapılır; taksit uygulanmaz.</li>
        <li>Lisans otomatik olarak yenilenmez; Alıcıdan tekrarlayan ödeme alınmaz.</li>
      </ul>

      <h2>Madde 4 — Teslimat</h2>
      <p>
        Lisans, ödemenin onaylanmasının hemen ardından Alıcının hesabına elektronik ortamda tanımlanır ve müşteri
        panelinde görüntülenir. Fiziksel teslimat yapılmaz. Ödeme onayının gecikmesi hâlinde teslim, onayın Satıcıya
        ulaştığı anda gerçekleşir.
      </p>

      <h2>Madde 5 — Lisans koşulları</h2>
      <p>
        Lisans; kişisel, devredilemez ve münhasır olmayan bir kullanım hakkı verir ve paketin bilgisayar sınırı içinde
        kullanılır. Kullanıma ilişkin ayrıntılar <TextLink href="/yasal/kullanim-kosullari">kullanım koşullarında</TextLink>{" "}
        düzenlenmiştir. Koşulların ihlali hâlinde Satıcı lisansı askıya alabilir veya iptal edebilir.
      </p>

      <h2>Madde 6 — Cayma hakkı</h2>
      <p>
        Ürün, elektronik ortamda anında teslim edilen gayrimaddi bir mal (dijital içerik) olduğundan, Mesafeli
        Sözleşmeler Yönetmeliği’nin 15. maddesinin birinci fıkrasının (ğ) bendi uyarınca cayma hakkı bulunmamaktadır.
        Alıcı, sipariş sırasında bu hususu ayrıca onaylamıştır.
      </p>

      <h2>Madde 7 — Ayıplı ifa ve iade</h2>
      <p>
        Lisansın teslim edilmemesi veya yazılımın sistem gereksinimlerini karşılayan bir bilgisayarda lisans nedeniyle
        çalışmaması hâlinde Alıcı, Satıcıya başvurarak sorunun giderilmesini, lisansın yenisiyle değiştirilmesini veya
        bedel iadesini talep edebilir. Ayrıntılar{" "}
        <TextLink href="/yasal/iptal-ve-iade">cayma, iptal ve iade koşullarında</TextLink> yer alır.
      </p>

      <h2>Madde 8 — Sorumluluk</h2>
      <p>
        Yazılımın ürettiği analizler yatırım tavsiyesi değildir; Satıcı hiçbir kazanç taahhüdünde bulunmaz. Alıcının
        işlem kararları ve sonuçları Alıcıya aittir (bkz. <TextLink href="/yasal/risk-bildirimi">risk bildirimi</TextLink>).
        Satıcının sorumluluğu, kanunen sınırlanamayan hâller saklı kalmak kaydıyla, ödenen lisans bedeli ile sınırlıdır.
      </p>

      <h2>Madde 9 — Uyuşmazlıkların çözümü</h2>
      <p>
        Bu sözleşmeden doğan uyuşmazlıklarda, Ticaret Bakanlığınca ilan edilen parasal sınırlar dahilinde tüketici hakem
        heyetleri, bu sınırları aşan durumlarda tüketici mahkemeleri yetkilidir.
      </p>

      <h2>Madde 10 — Yürürlük</h2>
      <p>
        Alıcı, ödeme sayfasında ön bilgilendirme formunu ve bu sözleşmeyi okuyup onayladığında sözleşme kurulmuş olur.
        Onay anındaki metin sürümü, siparişle birlikte saklanır ve talep hâlinde Alıcıya iletilir.
      </p>
    </LegalPage>
  );
}
