import { Download, Monitor, ShieldCheck, Smartphone } from "lucide-react";
import type { Metadata } from "next";

import { IconBox } from "@/components/IconBox";
import { RiskNotice } from "@/components/RiskNotice";
import { Card, Container, LinkButton, Notice, PageHeader } from "@/components/ui";
import { formatDate } from "@/lib/format";
import { fetchReleases, fileName, formatSize, type Release } from "@/lib/releases";

export const metadata: Metadata = {
  title: "İndir",
  description: "AI Trading Intelligence Windows uygulamasını ve iPhone uygulamasını indirin; kurulum adımları ve dosya doğrulama.",
};

const DEFAULT_MIN_OS = "Windows 10 veya Windows 11 (64 bit)";

const STEPS = [
  {
    title: "Kurulum paketini indirin",
    text: "Dosya yalnızca canarslan.net.tr üzerinden dağıtılır. Başka bir siteden gelen kurulum paketlerini çalıştırmayın.",
  },
  {
    title: "Kurun",
    text: "Kurulum kullanıcı hesabınıza yapılır, yönetici yetkisi istemez. İşlem motoru uygulamayla birlikte kurulur ve yalnızca sizin bilgisayarınızda çalışır.",
  },
  {
    title: "Lisansınızı etkinleştirin",
    text: "Uygulama ilk açılışta lisans anahtarınızı ister. Anahtarınızı müşteri panelinden görebilirsiniz; 7 günlük deneme ile de başlayabilirsiniz.",
  },
  {
    title: "Binance API anahtarını güvenli bağlayın",
    text: "Önce Binance Demo Trading anahtarıyla (demo.binance.com → API Management, sahte bakiye) deneyin. Gerçek hesapta anahtara yalnızca okuma ve işlem izni verin; para çekme (withdraw) iznini asla açmayın ve IP kısıtlaması kullanın.",
  },
];

function WindowsCard({ release, reachable }: { release: Release | null; reachable: boolean }) {
  if (!release) {
    return (
      <Card as="section" className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <IconBox icon={Monitor} />
          <h2 id="windows" className="text-xl font-semibold text-fg">
            Windows uygulaması
          </h2>
        </div>
        <Notice tone="info" title="İndirme yakında açılacak" role="status">
          {reachable
            ? "Windows kurulum paketi henüz yayınlanmadı. Hesap oluşturursanız ilk sürüm çıktığında sizi bilgilendiririz."
            : "Sürüm bilgisi şu anda yüklenemedi. Lütfen biraz sonra tekrar deneyin."}
        </Notice>
        <div className="flex flex-wrap gap-3">
          <LinkButton href="/kayit">Hesap oluştur</LinkButton>
          <LinkButton href="/paketler" variant="secondary">
            Paketleri incele
          </LinkButton>
        </div>
      </Card>
    );
  }
  const name = fileName(release.download_url);
  return (
    <Card as="section" className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <IconBox icon={Monitor} />
          <div>
            <h2 id="windows" className="text-xl font-semibold text-fg">
              Windows uygulaması
            </h2>
            <p className="text-sm text-muted" data-testid="windows-version">
              Sürüm {release.version} · {formatDate(release.published_at)}
            </p>
          </div>
        </div>
        <a
          href={release.download_url}
          rel="noopener"
          className="inline-flex items-center justify-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-accent-fg shadow-sm transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <Download aria-hidden="true" className="h-4 w-4" />
          Windows için indir
        </a>
      </div>

      <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-muted">Gereksinim</dt>
          <dd className="font-medium text-fg">{release.min_os || DEFAULT_MIN_OS}</dd>
        </div>
        <div>
          <dt className="text-muted">Dosya boyutu</dt>
          <dd className="font-medium text-fg">{formatSize(release.size_bytes)}</dd>
        </div>
        <div>
          <dt className="text-muted">Dosya</dt>
          <dd className="break-all font-medium text-fg">{name}</dd>
        </div>
      </dl>

      {release.signed ? (
        <Notice tone="success" title="Kod imzalı">
          Kurulum paketi dijital olarak imzalıdır. Windows, yayımcıyı “AI Trading Intelligence” olarak gösterir.
        </Notice>
      ) : (
        <Notice tone="warning" title="Bu sürüm henüz kod imzalı değil">
          Windows SmartScreen “Windows bilgisayarınızı korudu” uyarısı gösterebilir. Çalıştırmadan önce dosyanın
          özetini aşağıdaki komutla doğrulayın; özet eşleşmiyorsa dosyayı çalıştırmayın ve bize bildirin.
        </Notice>
      )}

      {release.sha256 ? (
        <div>
          <h3 className="text-sm font-semibold text-fg">Dosyayı doğrulayın (SHA-256)</h3>
          <code data-testid="windows-sha256" className="mt-2 block break-all rounded-lg bg-surface-2 px-3 py-2 font-mono text-sm text-fg">
            {release.sha256}
          </code>
          <p className="mt-3 text-sm text-muted">İndirdiğiniz klasörde PowerShell açıp çalıştırın; çıkan değer yukarıdakiyle aynı olmalı:</p>
          <code className="mt-2 block break-all rounded-lg bg-surface-2 px-3 py-2 font-mono text-sm text-fg">
            {`(Get-FileHash ".\\${name}" -Algorithm SHA256).Hash.ToLower()`}
          </code>
        </div>
      ) : null}

      {release.notes ? (
        <div>
          <h3 className="text-sm font-semibold text-fg">Bu sürümde</h3>
          <p className="mt-2 whitespace-pre-line text-sm text-muted">{release.notes}</p>
        </div>
      ) : null}
    </Card>
  );
}

function IosCard({ release }: { release: Release | null }) {
  return (
    <Card as="section" className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <IconBox icon={Smartphone} />
        <div>
          <h2 id="iphone" className="text-xl font-semibold text-fg">
            iPhone uygulaması
          </h2>
          {release ? <p className="text-sm text-muted">Sürüm {release.version}</p> : null}
        </div>
      </div>
      <p className="text-sm text-muted">
        Bilgisayarınızdaki motoru telefondan izleyin ve kontrol edin. Telefon ile bilgisayar arasındaki her mesaj uçtan uca
        şifrelidir; telefon Binance anahtarı tutmaz.
      </p>
      {release ? (
        <a
          href={release.download_url}
          rel="noopener"
          className="inline-flex w-fit items-center justify-center gap-2 rounded-full border border-border-strong/40 bg-surface px-5 py-2.5 text-sm font-semibold text-fg transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <Smartphone aria-hidden="true" className="h-4 w-4" />
          App Store’da aç
        </a>
      ) : (
        <Notice tone="info" role="status">
          iPhone uygulaması App Store incelemesinden sonra burada yayınlanacak.
        </Notice>
      )}
    </Card>
  );
}

export default async function DownloadPage() {
  const { releases, reachable } = await fetchReleases();
  return (
    <>
      <PageHeader
        eyebrow="İndir"
        title="Uygulamayı indirin"
        lead="AI Trading Intelligence kendi Windows bilgisayarınızda çalışır. Anahtarlarınız bilgisayarınızda şifreli kalır; sunucumuza gönderilmez."
      />
      <Container className="py-12">
        <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
          <WindowsCard release={releases.windows} reachable={reachable} />
          <IosCard release={releases.ios} />
        </div>

        <section aria-labelledby="kurulum" className="mt-14">
          <h2 id="kurulum" className="text-2xl font-semibold tracking-tight text-fg">
            Kurulum adımları
          </h2>
          <ol className="mt-6 grid gap-4 md:grid-cols-2">
            {STEPS.map((step, index) => (
              <li key={step.title}>
                <Card className="h-full">
                  <p className="text-sm font-semibold text-accent-text">Adım {index + 1}</p>
                  <h3 className="mt-1 font-semibold text-fg">{step.title}</h3>
                  <p className="mt-2 text-sm text-muted">{step.text}</p>
                </Card>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="guvenlik" className="mt-14 grid gap-6 md:grid-cols-2">
          <Card>
            <div className="flex items-center gap-3">
              <IconBox icon={ShieldCheck} />
              <h2 id="guvenlik" className="text-lg font-semibold text-fg">
                Güvenli başlangıç
              </h2>
            </div>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-muted">
              <li>Uygulama ilk açılışta sanal işlem (paper trading) modunda başlar.</li>
              <li>Gerçek parayla işlem ancak siz açıkça etkinleştirdiğinizde ve risk sınırlarınızı belirledikten sonra açılır.</li>
              <li>Acil durdurma düğmesi tüm otomatik işlemleri anında durdurur.</li>
            </ul>
          </Card>
          <Card>
            <div className="flex items-center gap-3">
              <IconBox icon={Monitor} />
              <h2 className="text-lg font-semibold text-fg">Sistem gereksinimleri</h2>
            </div>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-muted">
              <li>{releases.windows?.min_os || DEFAULT_MIN_OS}</li>
              <li>Kesintisiz internet bağlantısı (motor bilgisayarınız açıkken çalışır)</li>
              <li>iPhone uygulaması için iOS 17 veya üzeri</li>
            </ul>
          </Card>
        </section>

        <div className="mt-12 max-w-3xl">
          <RiskNotice />
        </div>
      </Container>
    </>
  );
}
