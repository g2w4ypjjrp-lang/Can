import type { Metadata } from "next";

import { LegalPage } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Risk bildirimi",
  description: "Kripto varlık işlemlerinin riskleri ve yazılımın sınırları hakkında bilgilendirme.",
};

export default function RiskDisclosurePage() {
  return (
    <LegalPage title="Risk bildirimi" updated="8 Kasım 2026">
      <p>
        Bu bildirim, AI Trading Intelligence yazılımını (“Yazılım”) kullanmadan önce bilmeniz gereken başlıca riskleri
        özetler. Yazılımı kullanarak bu riskleri anladığınızı ve kabul ettiğinizi beyan etmiş olursunuz.
      </p>

      <h2>1. Yatırım tavsiyesi değildir</h2>
      <p>
        Yazılım bir analiz ve işlem aracıdır. Ürettiği analizler, puanlar, fırsat bildirimleri ve stratejiler yatırım
        tavsiyesi, yatırım danışmanlığı veya portföy yönetimi hizmeti değildir. Yatırım kararları ve sonuçları
        tamamen size aittir.
      </p>

      <h2>2. Kazanç garantisi yoktur</h2>
      <p>
        Yazılım hiçbir koşulda kâr veya belirli bir getiri sağlayacağını taahhüt etmez. Kripto varlık işlemlerinde
        yatırdığınız paranın bir kısmını veya tamamını kaybedebilirsiniz. Kaybetmeyi göze alamayacağınız parayla
        işlem yapmayın.
      </p>

      <h2>3. Piyasa riskleri</h2>
      <ul>
        <li>Kripto varlık fiyatları çok kısa sürede çok sert değişebilir.</li>
        <li>Düşük likiditede emirler beklenenden kötü fiyattan gerçekleşebilir (kayma) veya hiç gerçekleşmeyebilir.</li>
        <li>
          Vadeli işlemlerde kaldıraç kayıpları büyütür; teminatınızın tamamı tasfiye (likidasyon) yoluyla kaybedilebilir.
          Fonlama ücretleri pozisyon maliyetini artırabilir.
        </li>
        <li>Düzenleyici kararlar, borsa kesintileri veya bir varlığın listeden çıkarılması fiyatları ve erişimi etkileyebilir.</li>
      </ul>

      <h2>4. Modellerin ve testlerin sınırları</h2>
      <ul>
        <li>Yapay zekâ ve istatistik modelleri geçmiş veriden öğrenir; piyasa koşulları değiştiğinde hatalı sonuç verebilir.</li>
        <li>
          Backtest ve sanal işlem sonuçları gerçek işlemlerin sonuçlarını göstermez. Gerçek işlemlerde kayma, gecikme,
          kısmi gerçekleşme ve ücretler sonuçları kötüleştirebilir.
        </li>
        <li>Geçmiş performans gelecekteki sonuçların göstergesi değildir.</li>
      </ul>

      <h2>5. Teknik riskler</h2>
      <ul>
        <li>
          Motor kendi bilgisayarınızda çalışır. Elektrik veya internet kesintisi, bilgisayarın kapanması, uyku modu ya
          da güncellemeler sırasında motor çalışmaz; açık pozisyonlar izlenemeyebilir.
        </li>
        <li>Borsa API'sindeki kesinti, gecikme veya hatalar emirlerin gönderilmesini veya iptalini engelleyebilir.</li>
        <li>Yazılımda, her türlü özene rağmen, hata bulunabilir.</li>
      </ul>
      <p>
        Bu risklere karşı Yazılım; işlem başına risk sınırı, günlük zarar sınırı, açık pozisyon sınırı ve acil durdurma
        gibi korumalar içerir. Bu korumalar kaybı sınırlamaya yardımcı olur, ancak kayıp olmayacağını garanti etmez.
      </p>

      <h2>6. Hesap güvenliği</h2>
      <ul>
        <li>Borsa hesabınızın ve API anahtarlarınızın güvenliğinden siz sorumlusunuz. İki adımlı doğrulamayı kullanın.</li>
        <li>API anahtarında para çekme yetkisini açmayın; Yazılım bu yetkiye sahip anahtarları kabul etmez.</li>
        <li>Bilgisayarınızı güncel tutun ve zararlı yazılımlara karşı koruyun.</li>
      </ul>

      <h2>7. Gerçek parayla işlem</h2>
      <p>
        Yazılım varsayılan olarak sanal işlem ve Binance Demo Trading (sahte bakiye) ortamıyla çalışır. Gerçek hesapta işlemi açmak sizin ayrı ve açık
        onayınızı gerektirir. Bu onayı vermeden önce stratejinizi sanal ortamda yeterince test etmenizi ve küçük
        tutarlarla başlamanızı öneririz.
      </p>

      <h2>8. Vergi ve yasal yükümlülükler</h2>
      <p>
        Kripto varlık işlemlerinden doğan vergi ve bildirim yükümlülükleri size aittir. Bulunduğunuz ülkedeki
        mevzuata uygun hareket etmekten siz sorumlusunuz.
      </p>
    </LegalPage>
  );
}
