import Link from "next/link";

import { LogoMark } from "@/components/Logo";
import { Container } from "@/components/ui";

const NAV = [
  { href: "/ozellikler", label: "Özellikler" },
  { href: "/paketler", label: "Paketler" },
  { href: "/sss", label: "SSS" },
  { href: "/iletisim", label: "İletişim" },
];

const navLink =
  "rounded-md px-3 py-2 text-sm font-medium text-fg hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-surface/95 backdrop-blur">
      <Container className="flex h-16 items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-2.5 rounded-md focus-visible:outline-2 focus-visible:outline-accent">
          <LogoMark />
          <span className="text-base font-bold tracking-tight text-fg">
            AI Trading <span className="text-accent-text">Intelligence</span>
          </span>
        </Link>
        <nav aria-label="Ana menü" className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className={navLink}>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="hidden items-center gap-2 md:flex">
          <Link href="/giris" className={navLink}>
            Giriş yap
          </Link>
          <Link
            href="/kayit"
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Hesap oluştur
          </Link>
        </div>
        {/* Küçük ekran menüsü: JavaScript gerektirmeyen açılır liste. */}
        <details className="relative md:hidden">
          <summary className="cursor-pointer list-none rounded-md border border-border px-3 py-2 text-sm font-medium text-fg">
            Menü
          </summary>
          <nav aria-label="Mobil menü" className="absolute right-0 mt-2 w-56 rounded-xl border border-border bg-surface p-2 shadow-lg">
            <ul className="flex flex-col">
              {[...NAV, { href: "/giris", label: "Giriş yap" }, { href: "/kayit", label: "Hesap oluştur" }].map((item) => (
                <li key={item.href}>
                  <Link href={item.href} className={`block ${navLink}`}>
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </details>
      </Container>
    </header>
  );
}
