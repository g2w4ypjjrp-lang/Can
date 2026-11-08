import Link from "next/link";

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
      { href: "/iletisim", label: "İletişim" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-border bg-surface">
      <Container className="py-10">
        <div className="grid gap-8 sm:grid-cols-3">
          {GROUPS.map((group) => (
            <nav key={group.title} aria-label={group.title}>
              <h2 className="text-sm font-semibold text-fg">{group.title}</h2>
              <ul className="mt-3 space-y-2">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <Link href={link.href} className="text-sm text-muted hover:text-fg hover:underline">
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
          <p className="mt-4 text-xs text-muted">© {new Date().getFullYear()} AI Trading Intelligence. Binance, ilgili şirketlerin ticari markasıdır; bu ürün Binance ile bağlantılı değildir.</p>
        </div>
      </Container>
    </footer>
  );
}
