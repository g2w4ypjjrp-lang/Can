import type { Metadata } from "next";

import { LegalPage } from "@/components/LegalPage";
import { TextLink } from "@/components/ui";

export const metadata: Metadata = {
  title: "Cayma, iptal ve iade",
  description: "Lisans satışlarında cayma hakkı, iptal ve iade koşulları (taslak).",
};

export default function RefundPolicyPage() {
  return (
    <LegalPage title="Cayma, iptal ve iade" updated="9 Kasım 2026">
      <h2>1. Cayma hakkı</h2>
      <p>
        Lisanslar ödeme onayından hemen sonra elektronik ortamda teslim edilen dijital içeriktir. Mesafeli Sözleşmeler
        Yönetmeliği’nin 15. maddesinin birinci fıkrasının (ğ) bendi uyarınca bu tür sözleşmelerde cayma hakkı
        kullanılamaz; bu husus ödeme öncesinde ayrıca onayınıza sunulur.
      </p>
      <p>
        Satın almadan önce ürünü denemek isterseniz, satışta olduğu dönemlerde 7 günlük deneme paketini
        kullanabilirsiniz.
      </p>

      <h2>2. İade edilen durumlar</h2>
      <ul>
        <li>Ödemeniz alındığı hâlde lisans hesabınıza tanımlanmadıysa.</li>
        <li>Aynı sipariş için birden fazla tahsilat yapıldıysa (fazla tahsilat iade edilir).</li>
        <li>
          Lisans, sistem gereksinimlerini karşılayan bir bilgisayarda lisans kaynaklı bir sorun nedeniyle
          etkinleştirilemiyorsa ve sorun destek ekibimizce makul sürede giderilemezse.
        </li>
      </ul>
      <p>
        Piyasa koşulları, işlem sonuçları veya beklenen kazancın elde edilmemesi iade nedeni değildir; yazılım kazanç
        garantisi vermez (bkz. <TextLink href="/yasal/risk-bildirimi">risk bildirimi</TextLink>).
      </p>

      <h2>3. Nasıl başvurulur?</h2>
      <p>
        <TextLink href="/iletisim">İletişim formunda</TextLink> “Satış ve paketler” konusunu seçip sipariş numaranızı yazın.
        Başvurunuz incelenir ve sonucu e-posta ile bildirilir.
      </p>

      <h2>4. İade süreci</h2>
      <ul>
        <li>Onaylanan iadeler, ödemenin yapıldığı karta veya hesaba ödeme kuruluşu aracılığıyla yapılır.</li>
        <li>İade, onaydan itibaren en geç 14 gün içinde başlatılır; tutarın hesabınıza yansıma süresi bankanıza bağlıdır.</li>
        <li>Tam iade edilen siparişin lisansı iptal edilir ve bağlı bilgisayarlarda bir sonraki doğrulamada kullanılamaz hâle gelir.</li>
      </ul>

      <h2>5. Satıcının iptal hakkı</h2>
      <p>
        Kullanım koşullarının ihlali (ör. lisansın yeniden satışı, lisans denetimini aşma girişimi) hâlinde lisans
        askıya alınabilir veya iptal edilebilir; bu durumda bedel iadesi yapılmaz. Teknik bir hata nedeniyle hatalı
        fiyatla verilen siparişler, bedeli iade edilerek iptal edilebilir.
      </p>
    </LegalPage>
  );
}
