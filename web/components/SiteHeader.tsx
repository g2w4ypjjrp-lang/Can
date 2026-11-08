import Link from "next/link";

import { LogoMark } from "@/components/Logo";
import { MobileMenu } from "@/components/MobileMenu";
import { NavLinks, type NavItem } from "@/components/NavLinks";
import { Container } from "@/components/ui";

const NAV: NavItem[] = [
  { href: "/ozellikler", label: "Özellikler" },
  { href: "/paketler", label: "Paketler" },
  { href: "/sss", label: "SSS" },
  { href: "/iletisim", label: "İletişim" },
];

const navLink =
  "rounded-full px-3.5 py-2 text-sm font-medium text-muted transition-colors hover:text-fg focus-visible:outline-2 focus-visible:outline-accent";
const navActive = "bg-surface-2 text-fg";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border/70 bg-bg/80 backdrop-blur-xl">
      <Container className="flex h-16 items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-2.5 rounded-md focus-visible:outline-2 focus-visible:outline-accent">
          <LogoMark />
          <span className="text-[15px] font-semibold tracking-tight text-fg">
            AI Trading <span className="text-accent-text">Intelligence</span>
          </span>
        </Link>
        <nav aria-label="Ana menü" className="hidden items-center gap-1 rounded-full border border-border bg-surface/60 p-1 md:flex">
          <NavLinks items={NAV} linkClass={navLink} activeClass={navActive} />
        </nav>
        <div className="hidden items-center gap-2 md:flex">
          <Link href="/giris" className="rounded-full px-3.5 py-2 text-sm font-medium text-fg hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent">
            Giriş yap
          </Link>
          <Link
            href="/kayit"
            className="rounded-full bg-fg px-4 py-2 text-sm font-semibold text-bg shadow-sm transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Hesap oluştur
          </Link>
        </div>
        <MobileMenu items={[...NAV, { href: "/giris", label: "Giriş yap" }, { href: "/kayit", label: "Hesap oluştur" }]} />
      </Container>
    </header>
  );
}
