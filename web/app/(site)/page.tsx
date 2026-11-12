import {
  ArrowRight,
  Ban,
  BrainCircuit,
  ChartCandlestick,
  Check,
  ChevronDown,
  Download,
  FlaskConical,
  Gauge,
  KeyRound,
  LockKeyhole,
  Monitor,
  OctagonX,
  Radar,
  ShieldCheck,
  Smartphone,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { Architecture } from "@/components/home/Architecture";
import { DesktopViz, EquityViz, HeroVisual, PhoneViz, RadarViz, RiskViz, ScannerViz, ScoreRing } from "@/components/home/Visuals";
import { PriceTag } from "@/components/PriceTag";
import { RiskNotice } from "@/components/RiskNotice";
import { Backdrop, Badge, Container, IconTile, LinkButton, SectionTitle } from "@/components/ui";
import { FAQ } from "@/lib/faq";
import { fetchPlans } from "@/lib/plans";

const HIGHLIGHTS = [
  "Binance Spot",
  "USDⓈ-M vadeli",
  "14 hazır strateji",
  "Balina radarı",
  "Gerekçeli fırsat puanı",
  "Backtest",
  "Sanal işlem",
  "Demo Trading",
  "Risk kapısı",
  "Acil durdurma",
  "iPhone ile kontrol",
  "Face ID onayı",
  "Uçtan uca şifreleme",
  "Türkçe arayüz",
];

const NUMBERS = [
  { value: "14", label: "Hazır strateji", text: "Her biri backtest ve sanal işlemde ayrı ayrı ölçülür" },
  { value: "AES-256", label: "Uçtan uca şifreleme", text: "Telefon ile bilgisayar arasındaki her mesaj" },
  { value: "0", label: "Sunucuya giden API anahtarı", text: "Anahtarlar yalnızca bilgisayarınızda, şifreli" },
  { value: "1 tık", label: "Acil durdurma", text: "Bilgisayardan da telefondan da her an" },
];

const STRATEGIES = [
  "EMA trend takibi",
  "MACD momentum kesişimi",
  "RSI aşırı bölgeden dönüş",
  "Bollinger bandına dönüş",
  "Bollinger sıkışma kırılımı",
  "Donchian kanal kırılımı",
  "Ichimoku bulut trendi",
  "Stochastic RSI kesişimi",
  "VWAP geri alımı",
  "Hacimli itki",
  "Destek/direnç tepkisi",
  "Aşırı funding karşıtı",
  "Açık pozisyon teyitli trend",
  "Makine öğrenmesi modeli",
];

const STEPS: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: Download,
    title: "Kurun ve etkinleştirin",
    text: "Windows uygulamasını indirip kurun, lisans anahtarınızla etkinleştirin. Kiralık sunucuya (VDS) gerek yoktur.",
  },
  {
    icon: KeyRound,
    title: "Borsa hesabınızı bağlayın",
    text: "Önce Binance Demo Trading anahtarı (demo.binance.com) ile sahte bakiyeyle deneyin. Anahtar bilgisayarınızda şifreli saklanır; para çekme yetkisi açık anahtar kabul edilmez.",
  },
  {
    icon: FlaskConical,
    title: "Önce sanal ortamda deneyin",
    text: "Stratejileri geçmiş veride ve sanal bakiyeyle ölçün. Gerçek parayla işlem varsayılan olarak kapalıdır; yalnızca açık onayınızla açılır.",
  },
];

const SECURITY = [
  "API anahtarları Windows'un şifreleme altyapısıyla (DPAPI) bilgisayarınızda saklanır.",
  "Para çekme yetkisi açık olan API anahtarı reddedilir; yazılım para çekme işlemi yapamaz.",
  "Günlük zarar sınırına ulaşıldığında yeni işlem açılmaz; acil durdurma her an kullanılabilir.",
  "Telefondan yeni pozisyon açılamaz; pozisyon kapatma ve otomatik işlemi başlatma Face ID ister.",
  "Gerçek parayla işlem varsayılan olarak kapalıdır; açmak için ayrı ve açık onayınız gerekir.",
  "Önemli işlemler ve ayar değişiklikleri, sonradan değiştirilemeyen denetim kaydına yazılır.",
];

const HOME_FAQ = [1, 2, 3, 4].map((i) => FAQ[i]!).filter(Boolean);

export default async function HomePage() {
  const { plans } = await fetchPlans();
  const paid = plans.filter((p) => !p.is_trial && p.price_minor > 0);
  const cheapest = paid.sort((a, b) => a.price_minor - b.price_minor)[0];
  const trial = plans.find((p) => p.is_trial);

  return (
    <>
      {/* --- Kahraman -------------------------------------------------------------------------- */}
      <section className="relative overflow-hidden border-b border-border">
        <Backdrop />
        <Container className="relative grid items-center gap-16 pb-20 pt-14 sm:pt-20 lg:grid-cols-[1.02fr_1fr] lg:gap-14 lg:pb-28">
          <div>
            <Badge tone="accent" className="py-1.5 pl-1.5">
              <span className="rounded-full bg-brand px-2 py-0.5 text-[11px] font-semibold text-white">Yeni</span>
              iPhone ile uzaktan kontrol ve Face ID onayı
            </Badge>
            <h1 className="mt-7 text-[2.6rem] font-semibold leading-[1.04] tracking-[-0.035em] text-fg sm:text-6xl xl:text-[4.05rem]">
              Kripto piyasasını <span className="text-gradient">yapay zekâyla</span> analiz edin. Kontrol sizde kalsın.
            </h1>
            <p className="mt-7 max-w-xl text-lg leading-relaxed text-muted sm:text-xl">
              Canlı Binance verisi, balina radarı, gerekçeli fırsat puanı, backtest ve risk kapısı tek bir Windows
              uygulamasında. İşlem motoru kendi bilgisayarınızda çalışır; API anahtarlarınız sizden çıkmaz.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <LinkButton href="/kayit" size="lg">
                Hesap oluşturun <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </LinkButton>
              <LinkButton href="/indir" variant="secondary" size="lg">
                <Download aria-hidden="true" className="h-4 w-4" /> Uygulamayı indirin
              </LinkButton>
            </div>
            <ul className="mt-9 grid max-w-lg grid-cols-2 gap-x-6 gap-y-2.5 text-sm text-fg">
              {["Önce sanal işlem", "Binance Demo Trading desteği", "Çekim yetkili anahtar reddedilir", "Tamamen Türkçe arayüz"].map((item) => (
                <li key={item} className="flex items-center gap-2">
                  <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-success-bg text-success-fg">
                    <Check aria-hidden="true" className="h-3 w-3" strokeWidth={3} />
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <HeroVisual />
        </Container>
        <Container className="relative pb-10">
          <div className="max-w-3xl rounded-2xl border border-border bg-surface/70 px-4 py-3 backdrop-blur">
            <RiskNotice compact />
          </div>
        </Container>
      </section>

      {/* --- Akan şerit -------------------------------------------------------------------------- */}
      <section aria-label="Öne çıkanlar" className="border-b border-border bg-surface/60 py-5">
        <div className="marquee-mask overflow-hidden">
          <div className="marquee">
            {[0, 1].map((copy) => (
              <ul key={copy} aria-hidden={copy === 1 ? true : undefined} className="flex shrink-0 gap-3 pr-3">
                {HIGHLIGHTS.map((item) => (
                  <li key={item} className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-border bg-bg/70 px-4 py-2 text-sm font-medium text-fg">
                    <Sparkles aria-hidden="true" className="h-3.5 w-3.5 text-accent-text" />
                    {item}
                  </li>
                ))}
              </ul>
            ))}
          </div>
        </div>
      </section>

      {/* --- Rakamlar --------------------------------------------------------------------------- */}
      <section aria-label="Rakamlarla" className="border-b border-border">
        <Container className="py-14">
          <ul className="grid gap-px overflow-hidden rounded-3xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
            {NUMBERS.map((n) => (
              <li key={n.label} className="bg-surface p-7">
                <p className="text-gradient text-4xl font-semibold tracking-tight sm:text-5xl">{n.value}</p>
                <p className="mt-3 font-semibold text-fg">{n.label}</p>
                <p className="mt-1 text-sm text-muted">{n.text}</p>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      {/* --- Özellikler (bento) ------------------------------------------------------------------ */}
      <section aria-labelledby="ozellikler" className="relative">
        <Container className="py-24">
          <SectionTitle
            id="ozellikler"
            eyebrow="Özellikler"
            title="Analiz, test ve kontrol tek uygulamada"
            lead="Veriden karara, testten uygulamaya: piyasayı izlemek, stratejinizi ölçmek ve riskinizi sınırlamak için gereken araçlar."
          />
          <div className="reveal">
          <ul className="mt-14 grid gap-5 lg:grid-cols-6">
            <li className="card-lift flex flex-col gap-6 rounded-3xl border border-border bg-surface p-7 lg:col-span-4">
              <div className="flex items-start gap-4">
                <IconTile icon={ChartCandlestick} />
                <div>
                  <h3 className="text-xl font-semibold text-fg">Canlı piyasa verisi ve tarama</h3>
                  <p className="mt-2 text-muted">
                    Spot ve vadeli piyasalarda uygun pariteleri hacim, oynaklık, trend ve likiditeye göre sürekli sıralar;
                    bağlantı koparsa kendiliğinden yeniden kurar.
                  </p>
                </div>
              </div>
              <ScannerViz />
            </li>
            <li className="card-lift flex flex-col gap-6 rounded-3xl border border-border bg-surface p-7 lg:col-span-2">
              <div>
                <IconTile icon={Radar} tone="violet" />
                <h3 className="mt-4 text-xl font-semibold text-fg">Balina radarı</h3>
                <p className="mt-2 text-muted">Büyük işlemler, emir defteri duvarları, tasfiye zincirleri ve büyük oyuncu pozisyonlanması.</p>
              </div>
              <RadarViz />
            </li>
            <li className="card-lift flex flex-col gap-6 rounded-3xl border border-border bg-surface p-7 lg:col-span-2">
              <div>
                <IconTile icon={BrainCircuit} tone="cyan" />
                <h3 className="mt-4 text-xl font-semibold text-fg">Gerekçeli yapay zekâ analizi</h3>
                <p className="mt-2 text-muted">Model bilgisayarınızda eğitilir; her parite için gerekçeli, puanlı analiz üretir. Analizler olasılık tahminidir.</p>
              </div>
              <ScoreRing />
            </li>
            <li className="card-lift flex flex-col gap-6 rounded-3xl border border-border bg-surface p-7 lg:col-span-2">
              <div>
                <IconTile icon={FlaskConical} />
                <h3 className="mt-4 text-xl font-semibold text-fg">Backtest ve sanal işlem</h3>
                <p className="mt-2 text-muted">Stratejileri önce geçmiş veride, sonra canlı fiyatlarla sanal bakiyede ölçün.</p>
              </div>
              <EquityViz />
            </li>
            <li className="card-lift flex flex-col gap-6 rounded-3xl border border-border bg-surface p-7 lg:col-span-2">
              <div>
                <IconTile icon={Gauge} tone="success" />
                <h3 className="mt-4 text-xl font-semibold text-fg">Risk yönetimi</h3>
                <p className="mt-2 text-muted">Her emir gönderilmeden önce risk kapısından geçer; sınırlarınızı sistem aşamaz.</p>
              </div>
              <RiskViz />
            </li>
          </ul>
          <div className="mt-8 flex justify-center">
            <LinkButton href="/ozellikler" variant="secondary">
              Tüm özellikleri inceleyin <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </LinkButton>
          </div>
          </div>
        </Container>
      </section>

      {/* --- Nasıl çalışır ----------------------------------------------------------------------- */}
      <section aria-labelledby="nasil-calisir" className="relative overflow-hidden border-y border-border bg-surface">
        <div aria-hidden="true" className="bg-dots absolute inset-0" />
        <Container className="relative py-24">
          <SectionTitle id="nasil-calisir" eyebrow="Başlangıç" title="Üç adımda başlayın" center />
          <ol className="reveal relative mt-16 grid gap-8 md:grid-cols-3">
            <li aria-hidden="true" className="absolute left-[16%] right-[16%] top-7 hidden h-px bg-gradient-to-r from-transparent via-border-strong to-transparent md:block" />
            {STEPS.map((step, index) => (
              <li key={step.title} className="relative text-center">
                <span className="relative mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand text-white shadow-glow">
                  <step.icon aria-hidden="true" className="h-6 w-6" />
                  <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-xs font-bold text-fg">
                    {index + 1}
                  </span>
                </span>
                <h3 className="mt-6 text-lg font-semibold text-fg">{step.title}</h3>
                <p className="mx-auto mt-2 max-w-xs text-muted">{step.text}</p>
              </li>
            ))}
          </ol>
        </Container>
      </section>

      {/* --- Güvenlik mimarisi -------------------------------------------------------------------- */}
      <section aria-labelledby="guvenlik" className="relative">
        <Container className="py-24">
          <div className="grid gap-12 lg:grid-cols-[1fr_1.1fr] lg:items-end">
            <SectionTitle
              id="guvenlik"
              eyebrow="Güvenlik"
              title="Anahtarlarınız bilgisayarınızdan çıkmaz"
              lead="Telefonunuzdan gelen komutlar kriptografik olarak imzalanır ve uçtan uca şifrelenir; aradaki sunucu içeriği göremez. Sistem, kendi koyduğunuz risk sınırlarını aşamaz."
            />
            <div className="flex flex-wrap gap-2 lg:justify-end">
              <Badge tone="accent" className="px-3.5 py-1.5 text-sm">
                <LockKeyhole aria-hidden="true" className="h-4 w-4" /> AES-256-GCM
              </Badge>
              <Badge tone="success" className="px-3.5 py-1.5 text-sm">
                <Ban aria-hidden="true" className="h-4 w-4" /> Para çekme yok
              </Badge>
              <Badge tone="danger" className="px-3.5 py-1.5 text-sm">
                <OctagonX aria-hidden="true" className="h-4 w-4" /> Tek tuşla durdurma
              </Badge>
            </div>
          </div>
          <div className="reveal mt-14">
            <Architecture />
          </div>
          <ul className="mt-10 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {SECURITY.map((item) => (
              <li key={item} className="flex gap-3 rounded-2xl border border-border bg-surface p-4">
                <ShieldCheck aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-success-fg" />
                <span className="text-sm leading-relaxed text-fg">{item}</span>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      {/* --- Stratejiler -------------------------------------------------------------------------- */}
      <section aria-labelledby="stratejiler" className="relative overflow-hidden border-y border-border bg-surface">
        <Backdrop grid={false} />
        <Container className="relative grid gap-12 py-24 lg:grid-cols-[1fr_1.2fr] lg:items-center">
          <div>
            <SectionTitle
              id="stratejiler"
              eyebrow="Stratejiler"
              title="14 hazır strateji, her biri ayrı ölçülür"
              lead="Klasik ve yaygın bilinen kuralları uygulayan stratejiler hazır gelir. Hiçbirinin kârlı olduğu varsayılmaz: her biri backtest ve sanal işlem yarışmasında ayrı ayrı ölçülür, sonuçları karşılaştırırsınız."
            />
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton href="/ozellikler">
                Nasıl ölçülür? <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </LinkButton>
            </div>
          </div>
          <ul className="reveal flex flex-wrap gap-2.5">
            {STRATEGIES.map((name, i) => (
              <li
                key={name}
                className={`rounded-2xl border px-4 py-2.5 text-sm font-medium ${
                  i === STRATEGIES.length - 1 ? "gradient-border text-fg" : "border-border bg-bg/70 text-fg"
                }`}
              >
                {name}
              </li>
            ))}
          </ul>
        </Container>
      </section>

      {/* --- Platformlar -------------------------------------------------------------------------- */}
      <section aria-labelledby="platformlar">
        <Container className="py-24">
          <SectionTitle
            id="platformlar"
            eyebrow="Platformlar"
            title="Masaüstünde güç, cebinizde kontrol"
            lead="Analiz ve işlem bilgisayarınızda çalışır; iPhone uygulaması uçtan uca şifreli ve imzalı komutlarla bağlanır."
            center
          />
          <div className="reveal mt-14 grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <div className="relative overflow-hidden rounded-3xl border border-border bg-surface p-8">
              <div className="flex items-center gap-3">
                <IconTile icon={Monitor} />
                <div>
                  <h3 className="text-xl font-semibold text-fg">Windows uygulaması</h3>
                  <p className="text-sm text-muted">Windows 10 ve 11 · 64 bit</p>
                </div>
              </div>
              <ul className="mt-6 grid gap-2 text-sm text-fg sm:grid-cols-2">
                {["Grafik ve göstergeler", "Fırsat tarayıcı", "Balina radarı", "Backtest ve sanal işlem", "Risk ve acil durdurma", "Denetim kaydı"].map((item) => (
                  <li key={item} className="flex items-center gap-2">
                    <Check aria-hidden="true" className="h-4 w-4 text-success-fg" /> {item}
                  </li>
                ))}
              </ul>
              <div className="mt-8 flex flex-wrap gap-3">
                <LinkButton href="/indir">
                  <Download aria-hidden="true" className="h-4 w-4" /> İndirme sayfası
                </LinkButton>
              </div>
              <div className="mt-8">
                <DesktopViz />
              </div>
            </div>
            <div className="relative overflow-hidden rounded-3xl border border-border bg-surface p-8">
              <div className="flex items-center gap-3">
                <IconTile icon={Smartphone} tone="violet" />
                <div>
                  <h3 className="text-xl font-semibold text-fg">iPhone uygulaması</h3>
                  <p className="text-sm text-muted">iOS 17 ve üzeri</p>
                </div>
              </div>
              <p className="mt-4 text-sm leading-relaxed text-muted">
                Masaüstündeki QR kodu okutarak saniyeler içinde eşleşir. Durumu izleyin, bildirim alın, acil durdurmayı tek dokunuşla
                kullanın. Telefondan yeni pozisyon açılamaz ve para çekilemez.
              </p>
              <div className="mt-6">
                <PhoneViz />
              </div>
            </div>
          </div>
        </Container>
      </section>

      {/* --- Paketler ----------------------------------------------------------------------------- */}
      <section aria-labelledby="paketler-ozet" className="border-y border-border bg-surface">
        <Container className="grid gap-10 py-20 lg:grid-cols-[1.2fr_1fr] lg:items-center">
          <SectionTitle
            id="paketler-ozet"
            eyebrow="Paketler"
            title="Size uyan süreyi ve bilgisayar sayısını seçin"
            lead="Her pakette tüm özellikler ve iPhone uygulaması bulunur. Lisansınızı müşteri panelinden yönetirsiniz."
          />
          <div className="gradient-border rounded-3xl p-7 shadow-lift">
            {cheapest ? (
              <>
                <p className="text-sm font-medium text-muted">Başlangıç fiyatı</p>
                <PriceTag
                  className="mt-1"
                  minor={cheapest.price_minor}
                  currency={cheapest.currency}
                  listMinor={cheapest.list_price_minor}
                  percent={cheapest.campaign_percent}
                  priceClassName="text-4xl font-semibold tracking-tight text-fg"
                />
                <p className="mt-1 text-sm text-muted">{cheapest.name}</p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-muted">Fiyatlar</p>
                <p className="mt-1 text-3xl font-semibold tracking-tight text-fg">Yakında açıklanacak</p>
                <p className="mt-1 text-sm text-muted">Hesap oluşturursanız satış başladığında haberdar olursunuz.</p>
              </>
            )}
            <ul className="mt-6 space-y-2 text-sm text-fg">
              {["30 günden süresize kadar seçenek", "1, 2 veya 3 bilgisayar", trial ? "7 günlük deneme" : "Önce sanal işlemle deneme"].map((item) => (
                <li key={item} className="flex items-center gap-2">
                  <Check aria-hidden="true" className="h-4 w-4 text-success-fg" /> {item}
                </li>
              ))}
            </ul>
            <LinkButton href="/paketler" className="mt-7 w-full">
              Paketleri inceleyin <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </LinkButton>
          </div>
        </Container>
      </section>

      {/* --- SSS ---------------------------------------------------------------------------------- */}
      <section aria-labelledby="sss-ozet">
        <Container className="grid gap-12 py-24 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <SectionTitle id="sss-ozet" eyebrow="Sorular" title="Merak edilenler" lead="Güvenlik, anahtarlar ve gerçek hesap hakkında en sık sorulanlar." />
            <LinkButton href="/sss" variant="secondary" className="mt-8">
              Tüm sorular <ArrowRight aria-hidden="true" className="h-4 w-4" />
            </LinkButton>
          </div>
          <div className="space-y-3">
            {HOME_FAQ.map((item) => (
              <details key={item.q} className="group rounded-2xl border border-border bg-surface px-5 py-4 transition-colors open:bg-surface-2">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-base font-semibold text-fg">
                  {item.q}
                  <ChevronDown aria-hidden="true" className="h-5 w-5 shrink-0 text-muted transition-transform group-open:rotate-180" />
                </summary>
                {item.a.map((p) => (
                  <p key={p} className="mt-3 leading-relaxed text-fg">
                    {p}
                  </p>
                ))}
              </details>
            ))}
          </div>
        </Container>
      </section>

      {/* --- Son çağrı ---------------------------------------------------------------------------- */}
      <section aria-labelledby="baslayin">
        <Container className="pb-24">
          <div className="relative overflow-hidden rounded-[2.25rem] bg-brand px-8 py-14 text-white shadow-lift sm:px-14">
            <div aria-hidden="true" className="bg-dots absolute inset-0 opacity-50" />
            <div aria-hidden="true" className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-white/10" />
            <div className="relative flex flex-col items-start justify-between gap-8 lg:flex-row lg:items-center">
              <div>
                <h2 id="baslayin" className="text-3xl font-semibold tracking-tight sm:text-5xl">
                  Önce sanal ortamda deneyin.
                </h2>
                <p className="mt-4 max-w-xl text-lg text-white">
                  Hesabınızı oluşturun, uygulamayı kurun, stratejilerinizi gerçek para riske atmadan ölçün.
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <LinkButton href="/kayit" variant="light" size="lg">
                  Hesap oluştur <ArrowRight aria-hidden="true" className="h-4 w-4" />
                </LinkButton>
                <LinkButton href="/iletisim" variant="outlineLight" size="lg">
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
