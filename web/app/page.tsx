import { RiskNotice } from "@/components/RiskNotice";
import { Card, Container, LinkButton } from "@/components/ui";

const STEPS = [
  {
    title: "Kurun ve etkinleştirin",
    text: "Windows uygulamasını kurun, lisans anahtarınızla etkinleştirin. Kiralık sunucuya (VDS) gerek yoktur; motor kendi bilgisayarınızda çalışır.",
  },
  {
    title: "Borsa hesabınızı bağlayın",
    text: "Binance API anahtarınızı ekleyin. Anahtar bilgisayarınızda şifreli saklanır, bize gönderilmez. Para çekme yetkisi açık olan anahtar kabul edilmez.",
  },
  {
    title: "Önce sanal ortamda deneyin",
    text: "Stratejileri geçmiş veride test edin, sanal bakiye ve test ağında çalıştırın. Gerçek parayla işlem varsayılan olarak kapalıdır ve yalnızca sizin açık onayınızla açılır.",
  },
];

const FEATURES = [
  { title: "Canlı piyasa verisi ve tarama", text: "Spot ve vadeli piyasalarda yüzlerce coini hacim, oynaklık ve trend ölçütlerine göre sürekli tarar." },
  { title: "Balina takibi", text: "Büyük işlemleri, emir defteri duvarlarını, tasfiye zincirlerini ve büyük oyuncu pozisyonlanmasını izler; olağan dışı hareketlerde uyarır." },
  { title: "Yapay zekâ destekli analiz", text: "Göstergeleri, hacmi ve balina verisini birleştirip her coin için gerekçeli, puanlı bir analiz üretir." },
  { title: "Backtest ve sanal işlem", text: "Stratejinizi önce geçmiş veride, sonra gerçek zamanlı sanal bakiyeyle ölçün; komisyon ve kayma dâhil." },
  { title: "Risk yönetimi", text: "İşlem başına risk, günlük zarar sınırı, pozisyon limitleri ve tek tuşla acil durdurma." },
  { title: "iPhone ile uzaktan kontrol", text: "Durumu izleyin, bildirim alın, acil durdurmayı tek dokunuşla kullanın. Kritik komutlar Face ID ister." },
];

export default function HomePage() {
  return (
    <>
      <section className="border-b border-border bg-surface">
        <Container className="py-16 sm:py-24">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold tracking-wide text-accent-text">Windows · iPhone · Binance</p>
            <h1 className="mt-3 text-4xl font-bold tracking-tight text-fg sm:text-5xl">
              Kripto piyasasını kendi bilgisayarınızda, kendi kurallarınızla analiz edin
            </h1>
            <p className="mt-5 text-lg text-muted">
              Piyasa verisi, balina hareketleri, yapay zekâ destekli analiz, backtest ve risk yönetimi tek bir
              uygulamada. İşlem motoru bilgisayarınızda çalışır; API anahtarlarınız sizde kalır.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton href="/paketler">Paketleri inceleyin</LinkButton>
              <LinkButton href="/ozellikler" variant="secondary">
                Özellikler
              </LinkButton>
            </div>
            <div className="mt-8 max-w-2xl">
              <RiskNotice compact />
            </div>
          </div>
        </Container>
      </section>

      <section aria-labelledby="nasil-calisir">
        <Container className="py-16">
          <h2 id="nasil-calisir" className="text-2xl font-bold tracking-tight text-fg sm:text-3xl">
            Nasıl çalışır?
          </h2>
          <ol className="mt-8 grid gap-6 md:grid-cols-3">
            {STEPS.map((step, index) => (
              <Card as="li" key={step.title}>
                <p className="text-sm font-semibold text-accent-text">Adım {index + 1}</p>
                <h3 className="mt-2 text-lg font-semibold text-fg">{step.title}</h3>
                <p className="mt-2 text-muted">{step.text}</p>
              </Card>
            ))}
          </ol>
        </Container>
      </section>

      <section aria-labelledby="ozellikler" className="border-y border-border bg-surface">
        <Container className="py-16">
          <h2 id="ozellikler" className="text-2xl font-bold tracking-tight text-fg sm:text-3xl">
            Tek uygulamada analiz, test ve kontrol
          </h2>
          <ul className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature) => (
              <li key={feature.title} className="rounded-xl border border-border bg-bg p-6">
                <h3 className="text-lg font-semibold text-fg">{feature.title}</h3>
                <p className="mt-2 text-muted">{feature.text}</p>
              </li>
            ))}
          </ul>
          <div className="mt-8">
            <LinkButton href="/ozellikler" variant="secondary">
              Tüm özellikleri görün
            </LinkButton>
          </div>
        </Container>
      </section>

      <section aria-labelledby="guvenlik">
        <Container className="py-16">
          <div className="grid gap-10 lg:grid-cols-2">
            <div>
              <h2 id="guvenlik" className="text-2xl font-bold tracking-tight text-fg sm:text-3xl">
                Güvenlik baştan tasarlandı
              </h2>
              <p className="mt-4 text-muted">
                Kontrol sizde kalır: anahtarlarınız bilgisayarınızdan çıkmaz, telefonunuzdan gelen komutlar
                kriptografik olarak imzalanır, sistem kendi koyduğunuz risk sınırlarını aşamaz.
              </p>
            </div>
            <ul className="space-y-4">
              {[
                "API anahtarları Windows'un şifreleme altyapısıyla (DPAPI) bilgisayarınızda saklanır.",
                "Para çekme yetkisi açık olan API anahtarı reddedilir; yazılım para çekme işlemi yapamaz.",
                "Günlük zarar sınırına ulaşıldığında yeni işlem açılmaz; acil durdurma her an kullanılabilir.",
                "Telefondan yeni pozisyon açılamaz; pozisyon kapatma ve otomatik işlemi başlatma Face ID ister.",
                "Gerçek parayla işlem varsayılan olarak kapalıdır; açmak için ayrı ve açık onayınız gerekir.",
              ].map((item) => (
                <li key={item} className="flex gap-3">
                  <span aria-hidden="true" className="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full bg-accent" />
                  <span className="text-fg">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </Container>
      </section>

      <section aria-labelledby="baslayin" className="border-t border-border bg-surface">
        <Container className="flex flex-col items-start justify-between gap-6 py-14 md:flex-row md:items-center">
          <div>
            <h2 id="baslayin" className="text-2xl font-bold tracking-tight text-fg">
              Önce sanal ortamda deneyin
            </h2>
            <p className="mt-2 text-muted">Hesabınızı oluşturun; paketler satışa açıldığında haberdar olun.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <LinkButton href="/kayit">Hesap oluştur</LinkButton>
            <LinkButton href="/iletisim" variant="secondary">
              Bize yazın
            </LinkButton>
          </div>
        </Container>
      </section>
    </>
  );
}
