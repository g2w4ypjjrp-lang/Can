import { ArrowUpRight, LockKeyhole, Monitor, Smartphone } from "lucide-react";
import Link from "next/link";

import { LogoMark, Wordmark } from "@/components/Logo";
import { RiskNotice } from "@/components/RiskNotice";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Container } from "@/components/ui";

const GROUPS = [
  {
    title: "Ürün",
    links: [
      { href: "/ozellikler", label: "Özellikler" },
      { href: "/paketler", label: "Paketler" },
      { href: "/indir", label: "İndir" },
      { href: "/sss", label: "Sık sorulan sorular" },
    ],
  },
  {
    title: "Hesap",
    links: [
      { href: "/giris", label: "Giriş yap" },
      { href: "/kayit", label: "Hesap oluştur" },
      { href: "/panel", label: "Müşteri paneli" },
      { href: "/iletisim", label: "İletişim" },
    ],
  },
  {
    title: "Yasal",
    links: [
      { href: "/yasal/kullanim-kosullari", label: "Kullanım koşulları" },
      { href: "/yasal/gizlilik", label: "Gizlilik ve KVKK" },
      { href: "/yasal/risk-bildirimi", label: "Risk bildirimi" },
      { href: "/yasal/mesafeli-satis-sozlesmesi", label: "Mesafeli satış sözleşmesi" },
      { href: "/yasal/iptal-ve-iade", label: "Cayma, iptal ve iade" },
    ],
  },
];

const FACTS = [
  { icon: Monitor, text: "Windows 10 / 11" },
  { icon: Smartphone, text: "iPhone · iOS 17+" },
  { icon: LockKeyhole, text: "Uçtan uca şifreli" },
];

export function SiteFooter() {
  return (
    <footer className="relative mt-auto overflow-hidden border-t border-border bg-surface">
      <div aria-hidden="true" className="glow absolute inset-0 opacity-70" />
      <Container className="relative pb-10 pt-16">
        <div className="grid gap-12 lg:grid-cols-[1.5fr_repeat(3,1fr)]">
          <div>
            <Link href="/" className="inline-flex items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-accent-text">
              <LogoMark className="h-9 w-9" />
              <Wordmark />
            </Link>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-muted">
              Kendi bilgisayarınızda çalışan kripto analiz ve işlem yazılımı. Anahtarlarınız sizde, kurallar sizin.
            </p>
            <ul className="mt-6 flex flex-wrap gap-2">
              {FACTS.map(({ icon: Icon, text }) => (
                <li key={text} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-bg/60 px-3 py-1 text-xs font-medium text-fg">
                  <Icon aria-hidden="true" className="h-3.5 w-3.5 text-accent-text" />
                  {text}
                </li>
              ))}
            </ul>
          </div>
          {GROUPS.map((group) => (
            <nav key={group.title} aria-label={group.title}>
              <h2 className="text-sm font-semibold text-fg">{group.title}</h2>
              <ul className="mt-4 space-y-2.5">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <Link href={link.href} className="group inline-flex items-center gap-1 text-sm text-muted transition-colors hover:text-fg">
                      {link.label}
                      <ArrowUpRight aria-hidden="true" className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="mt-14 rounded-3xl border border-border bg-bg/60 p-5">
          <RiskNotice compact />
        </div>
        <div className="mt-8 flex flex-col items-start justify-between gap-4 border-t border-border pt-6 sm:flex-row sm:items-center">
          <p className="text-xs text-muted">
            © {new Date().getFullYear()} AI Trading Intelligence · canarslan.net.tr. Binance, ilgili şirketlerin ticari
            markasıdır; bu ürün Binance ile bağlantılı değildir.
          </p>
          <ThemeToggle />
        </div>
      </Container>
    </footer>
  );
}
