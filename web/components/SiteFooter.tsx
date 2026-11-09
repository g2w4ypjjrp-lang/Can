import Link from "next/link";

import { LogoMark } from "@/components/Logo";
import { RiskNotice } from "@/components/RiskNotice";
import { Container } from "@/components/ui";

const GROUPS = [
  {
    title: "Ürün",
    links: [
      { href: "/ozellikler", label: "Özellikler" },
      { href: "/paketler", label: "Paketler" },
      { href: "/sss", label: "Sık sorulan sorular" },
    ],
  },
  {
    title: "Hesap",
    links: [
      { href: "/giris", label: "Giriş yap" },
      { href: "/kayit", label: "Hesap oluştur" },
      { href: "/panel", label: "Müşteri paneli" },
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
      { href: "/iletisim", label: "İletişim" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-border bg-surface">
      <Container className="py-12">
        <div className="grid gap-10 md:grid-cols-[1.4fr_repeat(3,1fr)]">
          <div>
            <div className="flex items-center gap-2.5">
              <LogoMark className="h-7 w-7" />
              <span className="text-sm font-semibold text-fg">AI Trading Intelligence</span>
            </div>
            <p className="mt-3 max-w-xs text-sm text-muted">
              Kendi bilgisayarınızda çalışan kripto analiz ve işlem yazılımı. Anahtarlarınız sizde, kurallar sizin.
            </p>
          </div>
          {GROUPS.map((group) => (
            <nav key={group.title} aria-label={group.title}>
              <h2 className="text-sm font-semibold text-fg">{group.title}</h2>
              <ul className="mt-3 space-y-2">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <Link href={link.href} className="text-sm text-muted transition-colors hover:text-fg">
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="mt-10 border-t border-border pt-6">
          <RiskNotice compact />
          <p className="mt-4 text-xs text-muted">
            © {new Date().getFullYear()} AI Trading Intelligence · canarslan.net.tr. Binance, ilgili şirketlerin ticari
            markasıdır; bu ürün Binance ile bağlantılı değildir.
          </p>
        </div>
      </Container>
    </footer>
  );
}
