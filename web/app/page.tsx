import {
  ArrowRight,
  Ban,
  BrainCircuit,
  ChartCandlestick,
  Check,
  FingerprintPattern,
  FlaskConical,
  Gauge,
  KeyRound,
  LockKeyhole,
  Monitor,
  OctagonX,
  Radar,
  ServerOff,
  ShieldCheck,
  Smartphone,
  Sparkles,
  WavesHorizontal,
  type LucideIcon,
} from "lucide-react";

import { IconBox } from "@/components/IconBox";
import { DesktopPreview, PhonePreview, ProductPreview } from "@/components/ProductPreview";
import { RiskNotice } from "@/components/RiskNotice";
import { Badge, Container, LinkButton, SectionTitle } from "@/components/ui";

const TRUST: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: ServerOff, title: "Kiralık sunucu yok", text: "Motor kendi bilgisayarınızda çalışır" },
  { icon: KeyRound, title: "Anahtarlar sizde", text: "API anahtarları bize gönderilmez" },
  { icon: Ban, title: "Para çekme yok", text: "Çekim yetkili anahtar reddedilir" },
  { icon: FingerprintPattern, title: "Face ID onayı", text: "Kritik telefon komutlarında" },
];

const FEATURES: { icon: LucideIcon; title: string; text: string; wide?: boolean }[] = [
  {
    icon: ChartCandlestick,
    title: "Canlı piyasa verisi ve tarama",
    text: "Spot ve vadeli piyasalarda tüm uygun pariteleri hacim, oynaklık, trend ve likiditeye göre sürekli sıralar; bağlantı koparsa kendiliğinden yeniden kurar.",
    wide: true,
  },
  {
    icon: Radar,
    title: "Balina takibi",
    text: "Büyük işlemleri, emir defteri duvarlarını, tasfiye zincirlerini ve büyük oyuncu pozisyonlanmasını izler; olağan dışı hareketlerde uyarır.",
  },
  {
    icon: BrainCircuit,
    title: "Yapay zekâ destekli analiz",
    text: "Model bilgisayarınızda eğitilir; her coin için gerekçeli, puanlı bir analiz üretir. Analizler olasılık tahminidir.",
  },
  {
    icon: FlaskConical,
    title: "Backtest ve sanal işlem",
    text: "14 hazır stratejiyi önce geçmiş veride, sonra canlı fiyatlarla sanal bakiyede ölçün; komisyon ve kayma dâhil.",
  },
  {
    icon: Gauge,
    title: "Risk yönetimi",
    text: "İşlem başına risk, günlük zarar sınırı, açık pozisyon sınırı ve tek tuşla acil durdurma. Her emir gönderilmeden önce kontrol edilir.",
  },
];

const STEPS = [
  {
    title: "Kurun ve etkinleştirin",
    text: "Windows uygulamasını kurun, lisans anahtarınızla etkinleştirin. Kiralık sunucuya (VDS) gerek yoktur.",
  },
  {
    title: "Borsa hesabınızı bağlayın",
    text: "Binance API anahtarınızı ekleyin. Anahtar bilgisayarınızda şifreli saklanır; para çekme yetkisi açık olan anahtar kabul edilmez.",
  },
  {
    title: "Önce sanal ortamda deneyin",
    text: "Stratejileri geçmiş veride ve sanal bakiyeyle test edin. Gerçek parayla işlem varsayılan olarak kapalıdır ve yalnızca açık onayınızla açılır.",
  },
];

const SECURITY = [
  "API anahtarları Windows'un şifreleme altyapısıyla (DPAPI) bilgisayarınızda saklanır.",
  "Para çekme yetkisi açık olan API anahtarı reddedilir; yazılım para çekme işlemi yapamaz.",
  "Günlük zarar sınırına ulaşıldığında yeni işlem açılmaz; acil durdurma her an kullanılabilir.",
  "Telefondan yeni pozisyon açılamaz; pozisyon kapatma ve otomatik işlemi başlatma Face ID ister.",
  "Gerçek parayla işlem varsayılan olarak kapalıdır; açmak için ayrı ve açık onayınız gerekir.",
];

export default function HomePage() {
  return (
    <>
      <section className="relative overflow-hidden border-b border-border">
        <div aria-hidden="true" className="glow absolute inset-0" />
        <div aria-hidden="true" className="bg-grid absolute inset-0" />
        <Container className="relative grid items-center gap-14 py-16 sm:py-24 lg:grid-cols-[1.05fr_1fr]">
          <div>
            <Badge>
              <Sparkles aria-hidden="true" className="h-3.5 w-3.5 text-accent-text" />
              Yeni: iPhone ile uzaktan kontrol
            </Badge>
            <p className="mt-6 text-sm font-semibold tracking-wide text-accent-text">Windows · iPhone · Binance</p>
            <h1 className="mt-2 text-4xl font-semibold tracking-tight text-fg sm:text-6xl sm:leading-[1.05]">
              Kripto piyasasını <span className="text-accent-text">kendi bilgisayarınızda</span>, kendi kurallarınızla
              analiz edin
            </h1>
            <p className="mt-6 max-w-xl text-lg text-muted">
              Piyasa verisi, balina hareketleri, yapay zekâ destekli analiz, backtest ve risk yönetimi tek bir
              uygulamada. İşlem motoru bilgisayarınızda çalışır; API anahtarlarınız sizde kalır.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton href="/paketler">
                Paketleri inceleyin <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </LinkButton>
              <LinkButton href="/ozellikler" variant="secondary">
                Özellikler
              </LinkButton>
            </div>
            <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-fg">
              {["Önce sanal işlem", "Test ağı desteği", "Türkçe arayüz"].map((item) => (
                <li key={item} className="flex items-center gap-2">
                  <Check aria-hidden="true" className="h-4 w-4 text-success-fg" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <ProductPreview />
        </Container>
        <Container className="relative pb-10">
          <div className="max-w-3xl">
            <RiskNotice compact />
          </div>
        </Container>
      </section>

      <section aria-label="Öne çıkanlar" className="border-b border-border bg-surface">
        <Container className="py-8">
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {TRUST.map((item) => (
              <li key={item.title} className="flex items-start gap-3">
                <IconBox icon={item.icon} />
                <div>
                  <p className="font-semibold text-fg">{item.title}</p>
                  <p className="text-sm text-muted">{item.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      <section aria-labelledby="ozellikler">
        <Container className="py-20">
          <SectionTitle
            id="ozellikler"
            eyebrow="Özellikler"
            title="Tek uygulamada analiz, test ve kontrol"
            lead="Veriden karara, testten uygulamaya: piyasayı izlemek, stratejinizi ölçmek ve riskinizi sınırlamak için gereken araçlar."
          />
          <ul className="mt-10 grid gap-4 md:grid-cols-3">
            {FEATURES.map((feature) => (
              <li
                key={feature.title}
                className={`card-lift rounded-2xl border border-border bg-surface p-6 ${feature.wide ? "md:col-span-2" : ""}`}
              >
                <IconBox icon={feature.icon} />
                <h3 className="mt-4 text-lg font-semibold text-fg">{feature.title}</h3>
                <p className="mt-2 text-muted">{feature.text}</p>
              </li>
            ))}
            <li className="flex flex-col items-start gap-4 rounded-2xl border border-border bg-surface p-6 sm:flex-row sm:items-center md:col-span-3">
              <IconBox icon={WavesHorizontal} />
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-fg">Ve daha fazlası</h3>
                <p className="mt-1 text-muted">Grafik ve gösterge analizi, fırsat puanı, strateji performans karşılaştırması, bildirimler.</p>
              </div>
              <LinkButton href="/ozellikler" variant="secondary">
                Tüm özellikler <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </LinkButton>
            </li>
          </ul>
        </Container>
      </section>

      <section aria-labelledby="platformlar" className="border-y border-border bg-surface">
        <Container className="py-20">
          <SectionTitle
            id="platformlar"
            eyebrow="Platformlar"
            title="Masaüstünde güç, cebinizde kontrol"
            lead="Analiz ve işlem bilgisayarınızda çalışır; iPhone uygulaması uçtan uca imzalı komutlarla bağlanır."
          />
          <div className="mt-10 grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-border bg-bg p-6">
              <div className="flex items-center gap-3">
                <IconBox icon={Monitor} />
                <h3 className="text-lg font-semibold text-fg">Windows uygulaması</h3>
              </div>
              <p className="mt-3 text-muted">
                Grafikler, tarayıcı, balina radarı, fırsatlar, backtest, sanal işlem, risk ve ayarlar tek uygulamada.
              </p>
              <div className="mt-6">
                <DesktopPreview />
              </div>
            </div>
            <div className="grid items-center gap-6 rounded-2xl border border-border bg-bg p-6 sm:grid-cols-[1fr_auto]">
              <div>
                <div className="flex items-center gap-3">
                  <IconBox icon={Smartphone} />
                  <h3 className="text-lg font-semibold text-fg">iPhone uygulaması</h3>
                </div>
                <p className="mt-3 text-muted">
                  Durumu izleyin, bildirim alın, acil durdurmayı tek dokunuşla kullanın. Telefondan yeni pozisyon
                  açılamaz ve para çekilemez.
                </p>
              </div>
              <PhonePreview />
            </div>
          </div>
        </Container>
      </section>

      <section aria-labelledby="nasil-calisir">
        <Container className="py-20">
          <SectionTitle id="nasil-calisir" eyebrow="Başlangıç" title="Nasıl çalışır?" />
          <ol className="mt-10 grid gap-4 md:grid-cols-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="relative rounded-2xl border border-border bg-surface p-6">
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-fg">
                  {index + 1}
                </span>
                <h3 className="mt-4 text-lg font-semibold text-fg">{step.title}</h3>
                <p className="mt-2 text-muted">{step.text}</p>
              </li>
            ))}
          </ol>
        </Container>
      </section>

      <section aria-labelledby="guvenlik" className="border-y border-border bg-surface">
        <Container className="grid gap-12 py-20 lg:grid-cols-2">
          <div>
            <SectionTitle
              id="guvenlik"
              eyebrow="Güvenlik"
              title="Güvenlik baştan tasarlandı"
              lead="Kontrol sizde kalır: anahtarlarınız bilgisayarınızdan çıkmaz, telefonunuzdan gelen komutlar kriptografik olarak imzalanır, sistem kendi koyduğunuz risk sınırlarını aşamaz."
            />
            <div className="mt-8 flex flex-wrap gap-3 text-sm">
              <Badge>
                <LockKeyhole aria-hidden="true" className="h-3.5 w-3.5 text-accent-text" />
                Uçtan uca imzalı komutlar
              </Badge>
              <Badge>
                <OctagonX aria-hidden="true" className="h-3.5 w-3.5 text-danger-fg" />
                Tek tuşla acil durdurma
              </Badge>
            </div>
          </div>
          <ul className="space-y-3">
            {SECURITY.map((item) => (
              <li key={item} className="flex gap-3 rounded-2xl border border-border bg-bg p-4">
                <ShieldCheck aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-success-fg" />
                <span className="text-fg">{item}</span>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      <section aria-labelledby="baslayin">
        <Container className="py-20">
          <div className="gradient-border relative overflow-hidden rounded-3xl p-8 sm:p-12">
            <div aria-hidden="true" className="glow absolute inset-0" />
            <div className="relative flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
              <div>
                <h2 id="baslayin" className="text-3xl font-semibold tracking-tight text-fg">
                  Önce sanal ortamda deneyin
                </h2>
                <p className="mt-2 max-w-xl text-muted">Hesabınızı oluşturun; paketler satışa açıldığında haberdar olun.</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <LinkButton href="/kayit">
                  Hesap oluştur <ArrowRight aria-hidden="true" className="h-4 w-4" />
                </LinkButton>
                <LinkButton href="/iletisim" variant="secondary">
                  Bize yazın
                </LinkButton>
              </div>
            </div>
          </div>
        </Container>
      </section>
    </>
  );
}
