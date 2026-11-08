import {
  BrainCircuit,
  ChartCandlestick,
  FlaskConical,
  Gauge,
  Monitor,
  Radar,
  Smartphone,
  TestTubeDiagonal,
  type LucideIcon,
} from "lucide-react";
import type { Metadata } from "next";

import { IconBox } from "@/components/IconBox";

import { RiskNotice } from "@/components/RiskNotice";
import { Card, Container, LinkButton, Notice, PageHeader } from "@/components/ui";

export const metadata: Metadata = {
  title: "Özellikler",
  description:
    "Piyasa tarama, balina radarı, yapay zekâ destekli analiz, 14 hazır strateji, backtest, sanal işlem, otomatik işlem, risk yönetimi ve iPhone ile uzaktan kontrol.",
};

interface Section {
  id: string;
  icon: LucideIcon;
  title: string;
  lead: string;
  points: string[];
}

const SECTIONS: Section[] = [
  {
    id: "veri",
    icon: ChartCandlestick,
    title: "Canlı piyasa verisi ve tarama",
    lead: "Binance spot ve vadeli (sürekli kontrat) piyasalarından gerçek zamanlı veri.",
    points: [
      "Fiyat, işlem, emir defteri ve fonlama verisi WebSocket akışlarıyla anlık güncellenir; bağlantı koparsa kendiliğinden yeniden kurulur.",
      "Tarayıcı tüm uygun pariteleri hacim, oynaklık, trend ve likidite ölçütlerine göre sürekli sıralar.",
      "Stabil coin pariteleri gibi işlem fırsatı taşımayan semboller evrenden otomatik çıkarılır.",
    ],
  },
  {
    id: "balina",
    icon: Radar,
    title: "Balina radarı",
    lead: "Büyük oyuncuların piyasadaki izlerini tek ekranda toplar.",
    points: [
      "Büyük işlemler ve aynı yönde kümelenen balina hareketleri.",
      "Emir defterindeki büyük alış/satış duvarları ve tasfiye (likidasyon) zincirleri.",
      "Büyük oyuncu pozisyonlanması ve geçmiş balina olaylarının fiyat etkisi istatistikleri.",
      "Zincir üstü büyük transfer takibi, herkese açık blokzincir verisi sağlayan bir veri sağlayıcısı bağlandığında etkinleşir.",
    ],
  },
  {
    id: "analiz",
    icon: BrainCircuit,
    title: "Yapay zekâ destekli analiz",
    lead: "Model bilgisayarınızda, sizin verinizle eğitilir; analiz gerekçesiyle birlikte gösterilir.",
    points: [
      "Teknik göstergeler, hacim, fonlama ve balina verilerinden oluşturulan özelliklerle eğitilen bir makine öğrenmesi modeli (LightGBM).",
      "Yürüyen pencereli eğitim ve doğrulama: model yalnızca geçmişi görerek değerlendirilir, geleceğe bakma hatası önlenir.",
      "Her fırsat, puanı ve gerekçesiyle sunulur. Analizler olasılık tahminidir, hatalı olabilir.",
    ],
  },
  {
    id: "strateji",
    icon: FlaskConical,
    title: "Strateji kütüphanesi ve backtest",
    lead: "14 hazır strateji ve gerçekçi maliyetlerle geçmiş veri testi.",
    points: [
      "Trend (EMA, Ichimoku), momentum (MACD, Stokastik RSI), ortalamaya dönüş (RSI, Bollinger), kırılım (Donchian, sıkışma), hacim, VWAP, destek/direnç, fonlama ve açık pozisyon temelli stratejiler ile model tabanlı strateji.",
      "Backtest komisyon ve kaymayı (slippage) hesaba katar; sonuçlar kâr/zarar, en büyük düşüş, isabet oranı gibi ölçütlerle raporlanır.",
      "Geçmiş veride iyi çalışan bir strateji gelecekte de çalışacak demek değildir; sonuçlar yalnızca karşılaştırma içindir.",
    ],
  },
  {
    id: "sanal",
    icon: TestTubeDiagonal,
    title: "Sanal işlem (paper trading) ve test ağı",
    lead: "Gerçek para riske atmadan, canlı piyasada deneyin.",
    points: [
      "Sanal bakiyeyle canlı fiyatlarla işlem; emir, komisyon ve kayma gerçeğe yakın benzetilir.",
      "Otomatik işlem motoru Binance test ağında çalışır; emirler gerçek borsa akışından geçer ama gerçek para kullanılmaz.",
      "Gerçek hesapta işlem varsayılan olarak kapalıdır ve yalnızca sizin ayrı ve açık onayınızla açılabilir.",
    ],
  },
  {
    id: "risk",
    icon: Gauge,
    title: "Risk yönetimi",
    lead: "Her emir, gönderilmeden önce risk kontrolünden geçer.",
    points: [
      "İşlem başına risk sınırı (varsayılan sermayenin %0,5'i), günlük zarar sınırı (varsayılan %2) ve en fazla açık pozisyon sayısı (varsayılan 3).",
      "Günlük zarar sınırına ulaşıldığında gün sonuna kadar yeni işlem açılmaz.",
      "Acil durdurma tüm otomatik işlemleri anında keser; masaüstünden veya telefondan tek dokunuşla kullanılır.",
      "Bağlantı, veri akışı veya hesap eşleşmesi bozulursa motor yeni işlem açmayı kendiliğinden durdurur.",
    ],
  },
  {
    id: "masaustu",
    icon: Monitor,
    title: "Windows uygulaması",
    lead: "Kiralık sunucu (VDS) gerekmez; motor kendi bilgisayarınızda çalışır.",
    points: [
      "Grafikler, tarayıcı, balina radarı, fırsatlar, backtest, sanal işlem, risk ve ayarlar tek uygulamada.",
      "API anahtarları Windows'un şifreleme altyapısıyla (DPAPI) yalnızca bilgisayarınızda saklanır.",
      "Para çekme yetkisi açık olan API anahtarı reddedilir; yazılım para çekme işlemi yapamaz.",
    ],
  },
  {
    id: "iphone",
    icon: Smartphone,
    title: "iPhone ile uzaktan kontrol",
    lead: "Bilgisayarınızdaki motoru telefondan güvenle izleyin.",
    points: [
      "Özet durum, açık pozisyonlar, fırsatlar ve balina uyarıları; önemli olaylarda bildirim.",
      "Telefon bilgisayarınızla QR kodla eşleşir. Her komut telefonunuzun güvenli donanımındaki anahtarla imzalanır; sunucumuz komut üretemez.",
      "Acil durdurma ve duraklatma tek dokunuş; pozisyon kapatma ve otomatik işlemi başlatma Face ID ister.",
      "Telefondan yeni pozisyon açılamaz, risk sınırları değiştirilemez, para çekilemez.",
    ],
  },
];

export default function FeaturesPage() {
  return (
    <>
      <PageHeader
        eyebrow="Ürün"
        title="Özellikler"
        lead="Veriden karara, testten uygulamaya: piyasayı izlemek, stratejinizi ölçmek ve riskinizi kontrol altında tutmak için gereken araçlar."
      />
      <Container className="py-12">
        <nav aria-label="Bu sayfada" className="mb-10">
          <ul className="flex flex-wrap gap-2">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a
                  href={`#${section.id}`}
                  className="inline-block rounded-full border border-border bg-surface px-3.5 py-1.5 text-sm text-fg transition-colors hover:bg-surface-2"
                >
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="grid gap-6 lg:grid-cols-2">
          {SECTIONS.map((section) => (
            <Card as="section" key={section.id} className="card-lift">
              <div className="flex items-center gap-3">
                <IconBox icon={section.icon} />
                <h2 id={section.id} className="scroll-mt-24 text-xl font-semibold text-fg">
                  {section.title}
                </h2>
              </div>
              <p className="mt-2 text-muted">{section.lead}</p>
              <ul className="mt-4 space-y-2.5">
                {section.points.map((point) => (
                  <li key={point} className="flex gap-3 text-fg">
                    <span aria-hidden="true" className="mt-2 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>

        <section aria-labelledby="gereksinimler" className="mt-12">
          <h2 id="gereksinimler" className="text-2xl font-bold tracking-tight text-fg">
            Sistem gereksinimleri
          </h2>
          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <Card>
              <h3 className="font-semibold text-fg">Bilgisayar</h3>
              <ul className="mt-3 space-y-1.5 text-muted">
                <li>Windows 10 veya 11, 64 bit</li>
                <li>En az 8 GB bellek önerilir (model eğitimi için)</li>
                <li>Kesintisiz internet bağlantısı</li>
                <li>Motor yalnızca bilgisayarınız açıkken çalışır</li>
              </ul>
            </Card>
            <Card>
              <h3 className="font-semibold text-fg">Telefon (isteğe bağlı)</h3>
              <ul className="mt-3 space-y-1.5 text-muted">
                <li>iOS 17 veya üzeri bir iPhone</li>
                <li>Face ID veya Touch ID önerilir</li>
                <li>Masaüstü uygulamasıyla QR kod üzerinden eşleştirme</li>
              </ul>
            </Card>
          </div>
        </section>

        <div className="mt-12">
          <Notice tone="info" title="Borsa hesabınız">
            Yazılım yalnızca sizin oluşturduğunuz ve yetkilendirdiğiniz API anahtarıyla, kendi Binance hesabınızda
            çalışır. Binance hesabı açmak ve API anahtarı oluşturmak sizin sorumluluğunuzdadır.
          </Notice>
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <LinkButton href="/paketler">Paketleri inceleyin</LinkButton>
          <LinkButton href="/sss" variant="secondary">
            Sık sorulan sorular
          </LinkButton>
        </div>
        <div className="mt-10 max-w-3xl">
          <RiskNotice />
        </div>
      </Container>
    </>
  );
}
