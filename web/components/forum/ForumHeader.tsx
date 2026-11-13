// Forum sayfalarının ortak üst kısmı (klasik forum düzeni): kısa başlık bandı, arama, menü
// çubuğu, hoş geldiniz çubuğu ve konum (breadcrumb). Sayfanın tek h1 başlığı buradadır.

import { ChevronRight, Home, PenSquare, Rocket, Search, Trophy } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ForumWelcome } from "@/components/forum/ForumWelcome";
import { CandleBackdrop } from "@/components/forum/Visuals";
import { Container } from "@/components/ui";

export interface Crumb {
  href?: string;
  label: string;
}

const MENU = [
  { key: "home", href: "/forum", label: "Forum ana sayfası", icon: Home },
  { key: "yeni-coin", href: "/forum?kategori=yeni-coin", label: "Yeni coinler", icon: Rocket },
  { key: "ranks", href: "/forum/rutbeler", label: "Rütbeler ve liderlik", icon: Trophy },
] as const;

export function ForumHeader({
  title,
  subtitle,
  active,
  crumbs = [],
  search,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  active?: (typeof MENU)[number]["key"] | "new";
  crumbs?: Crumb[];
  search?: { category?: string; q?: string };
}) {
  return (
    <>
      <header className="relative overflow-hidden border-b border-border">
        <CandleBackdrop className="pointer-events-none absolute inset-0 h-full w-full opacity-70" />
        <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-r from-bg via-bg/80 to-bg/40" />
        <Container className="relative flex flex-wrap items-center justify-between gap-4 py-6">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-text">
              <span aria-hidden="true" className="pulse-dot h-1.5 w-1.5 rounded-full bg-up text-up" /> Kripto topluluğu
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-fg">{title}</h1>
            {subtitle ? <div className="mt-0.5 text-[13px] text-muted">{subtitle}</div> : null}
          </div>
          <form action="/forum" method="get" role="search" className="flex w-full gap-2 sm:w-auto">
            {search?.category ? <input type="hidden" name="kategori" value={search.category} /> : null}
            <label htmlFor="forum-ara" className="visually-hidden">
              Forumda ara
            </label>
            <div className="relative flex-1 sm:w-60">
              <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
              <input
                id="forum-ara"
                name="ara"
                defaultValue={search?.q ?? ""}
                maxLength={80}
                placeholder="Coin, konu, kelime"
                className="h-9 w-full rounded-lg border border-border bg-surface pl-8 pr-3 text-[13px] text-fg placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent-text"
              />
            </div>
            <button type="submit" className="h-9 rounded-lg border border-border bg-surface-2 px-3.5 text-[13px] font-semibold text-fg hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent-text">
              Ara
            </button>
          </form>
        </Container>
      </header>
      <Container className="fb mt-4 space-y-2.5">
        <nav aria-label="Forum menüsü" className="fb-navbar">
          {MENU.map(({ key, href, label, icon: Icon }) => (
            <Link key={key} href={href} aria-current={active === key ? "page" : undefined} className="fb-navlink">
              <Icon aria-hidden="true" className="h-3.5 w-3.5 text-accent-text" /> {label}
            </Link>
          ))}
          <Link
            href="/forum/yeni"
            aria-current={active === "new" ? "page" : undefined}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-brand px-3.5 py-1.5 text-[13px] font-semibold text-white shadow-glow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text"
          >
            <PenSquare aria-hidden="true" className="h-3.5 w-3.5" /> Konu aç
          </Link>
        </nav>
        <ForumWelcome />
        {crumbs.length ? (
          <nav aria-label="Konum" className="flex flex-wrap items-center gap-1 text-[12.5px] text-muted">
            <Link href="/forum" className="underline-offset-4 hover:text-fg hover:underline">
              Kripto Forum
            </Link>
            {crumbs.map((c) => (
              <span key={c.label} className="inline-flex items-center gap-1">
                <ChevronRight aria-hidden="true" className="h-3 w-3" />
                {c.href ? (
                  <Link href={c.href} className="underline-offset-4 hover:text-fg hover:underline">
                    {c.label}
                  </Link>
                ) : (
                  <span className="max-w-[40ch] truncate text-fg">{c.label}</span>
                )}
              </span>
            ))}
          </nav>
        ) : null}
      </Container>
    </>
  );
}
