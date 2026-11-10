import Link from "next/link";

import { LogoMark, Wordmark } from "@/components/Logo";
import { MobileMenu } from "@/components/MobileMenu";
import { NavLinks, type NavItem } from "@/components/NavLinks";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Container, LinkButton } from "@/components/ui";

const NAV: NavItem[] = [
  { href: "/ozellikler", label: "Özellikler" },
  { href: "/paketler", label: "Paketler" },
  { href: "/indir", label: "İndir" },
  { href: "/sss", label: "SSS" },
  { href: "/iletisim", label: "İletişim" },
];

const navLink =
  "rounded-full px-3.5 py-1.5 text-sm font-medium text-muted transition-colors hover:text-fg focus-visible:outline-2 focus-visible:outline-accent-text";
const navActive = "bg-surface-3 text-fg shadow-sm";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-glass-border bg-glass-strong backdrop-blur-xl backdrop-saturate-150">
      <Container className="flex h-16 items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-accent-text">
          <LogoMark className="h-8 w-8" />
          <Wordmark />
        </Link>
        <nav aria-label="Ana menü" className="hidden items-center gap-0.5 rounded-full border border-border bg-surface/70 p-1 shadow-sm lg:flex">
          <NavLinks items={NAV} linkClass={navLink} activeClass={navActive} />
        </nav>
        <div className="hidden items-center gap-2 lg:flex">
          <ThemeToggle />
          <Link
            href="/giris"
            className="rounded-full px-3.5 py-2 text-sm font-medium text-fg transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-text"
          >
            Giriş yap
          </Link>
          <LinkButton href="/kayit" size="sm" className="px-4 py-2">
            Hesap oluştur
          </LinkButton>
        </div>
        <MobileMenu items={[...NAV, { href: "/giris", label: "Giriş yap" }, { href: "/kayit", label: "Hesap oluştur" }]} />
      </Container>
    </header>
  );
}
