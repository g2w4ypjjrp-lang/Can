import type { Metadata } from "next";

import { ChevronLeft, ChevronRight, PenSquare, Rocket, Search } from "lucide-react";
import Link from "next/link";

import { Board } from "@/components/forum/Board";
import { MarketTicker, QuotesProvider } from "@/components/forum/Market";
import { ForumSidebar } from "@/components/forum/Sidebar";
import { EmptyThreads, ThreadList } from "@/components/forum/ThreadList";
import { CATEGORY_META, CandleBackdrop } from "@/components/forum/Visuals";
import { Container, Notice } from "@/components/ui";
import { firstParam } from "@/lib/format";
import { fetchOverview, fetchTopics, isCategory, type ForumCategory } from "@/lib/forum";
import { fetchQuotes } from "@/lib/market";

export const metadata: Metadata = {
  title: "Kripto Forum",
  description: "Kripto topluluğu: yeni listelenen coinler, strateji ve analiz, sorular ve ekibin paylaştığı güncel haberler.",
};

function href(params: { kategori?: string; ara?: string; sayfa?: number }) {
  const query = new URLSearchParams();
  if (params.kategori) query.set("kategori", params.kategori);
  if (params.ara) query.set("ara", params.ara);
  if (params.sayfa && params.sayfa > 1) query.set("sayfa", String(params.sayfa));
  const text = query.toString();
  return text ? `/forum?${text}` : "/forum";
}

const chip =
  "inline-flex shrink-0 items-center gap-2 rounded-xl border px-3.5 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent-text";

export default async function ForumPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const rawCategory = firstParam(params.kategori);
  const category: ForumCategory | undefined = isCategory(rawCategory) ? rawCategory : undefined;
  const q = (firstParam(params.ara) ?? "").trim().slice(0, 80);
  const page = Math.max(1, Math.min(500, Number(firstParam(params.sayfa)) || 1));
  const [data, overview, quotes] = await Promise.all([fetchTopics({ category, q, page }), fetchOverview(), fetchQuotes()]);
  const filtered = Boolean(category || q);
  // Göreli zamanlar sunucuda bir kez hesaplanır.
  const now = Date.now();
  const totals = overview?.totals ?? { topics: 0, posts: 0, members: 0 };
  const listTitle = category ? CATEGORY_META[category].label : q ? `“${q}” araması` : "Son konular";

  return (
    <QuotesProvider initial={quotes}>
      <div className="stage">
        <MarketTicker />
        <header className="relative overflow-hidden border-b border-border">
          <CandleBackdrop className="pointer-events-none absolute inset-0 h-full w-full" />
          {/* Metnin olduğu sol taraf koyulaştırılır: mumlar okunurluğu bozmasın. */}
          <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-r from-bg/90 via-bg/60 to-transparent" />
          <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(60%_80%_at_15%_0%,rgba(79,120,255,0.28),transparent_60%),radial-gradient(50%_70%_at_90%_10%,rgba(167,139,250,0.22),transparent_60%)]" />
          <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-bg to-transparent" />
          <Container className="relative grid items-end gap-8 py-12 sm:py-16 lg:grid-cols-[1.3fr_1fr]">
            <div>
              <p className="inline-flex items-center gap-2 rounded-full border border-border bg-surface/80 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-accent-text backdrop-blur">
                <span aria-hidden="true" className="pulse-dot h-2 w-2 rounded-full bg-up text-up" /> Kripto topluluğu
              </p>
              <h1 className="mt-4 text-4xl font-bold tracking-tight text-fg sm:text-6xl sm:leading-[1.02]">
                {category ? (
                  <>
                    <span className="text-gradient">{CATEGORY_META[category].label}</span>
                  </>
                ) : (
                  <>
                    Kripto <span className="text-gradient">Forum</span>
                  </>
                )}
              </h1>
              <p className="mt-4 max-w-2xl text-lg leading-relaxed text-muted">
                {category
                  ? CATEGORY_META[category].hint
                  : "Yeni listelenen coinler, strateji ve analiz, sorular ve ekibin seçtiği güncel haberler. Her konu yayımlanmadan önce ekibimizce incelenir."}
              </p>
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <Link
                  href="/forum/yeni"
                  className="shine inline-flex items-center gap-2 rounded-xl bg-brand px-5 py-3 text-sm font-semibold text-white shadow-glow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text"
                >
                  <PenSquare aria-hidden="true" className="h-4 w-4" /> Konu aç
                </Link>
                <Link
                  href="/forum?kategori=yeni-coin"
                  className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface/80 px-5 py-3 text-sm font-semibold text-fg backdrop-blur hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-text"
                >
                  <Rocket aria-hidden="true" className="h-4 w-4 text-down" /> Yeni coinler
                </Link>
              </div>
            </div>
            <dl className="grid grid-cols-3 gap-3">
              {[
                ["Konu", totals.topics],
                ["Mesaj", totals.posts],
                ["Üye", totals.members],
              ].map(([label, value]) => (
                <div key={label} className="neon-card rounded-2xl p-4">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</dt>
                  <dd className="mt-1 text-3xl font-bold tabular text-fg">{value}</dd>
                </div>
              ))}
            </dl>
          </Container>
        </header>

        <Container className="grid gap-8 py-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0 space-y-8">
            <div className="space-y-3">
              <nav aria-label="Forum kategorileri" className="scrollbar-none -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0">
                <Link
                  href={href({ ara: q || undefined })}
                  aria-current={!category ? "page" : undefined}
                  className={`${chip} ${!category ? "border-accent-text/50 bg-surface-2 text-fg" : "border-border bg-surface text-muted hover:text-fg"}`}
                >
                  Tümü
                </Link>
                {(Object.keys(CATEGORY_META) as ForumCategory[]).map((code) => {
                  const meta = CATEGORY_META[code];
                  const Icon = meta.icon;
                  const active = category === code;
                  return (
                    <Link
                      key={code}
                      href={href({ kategori: code, ara: q || undefined })}
                      aria-current={active ? "page" : undefined}
                      className={`${chip} ${active ? "border-accent-text/50 bg-surface-2 text-fg" : "border-border bg-surface text-muted hover:text-fg"}`}
                    >
                      <span aria-hidden="true" className={`grid h-5 w-5 place-items-center rounded-md bg-gradient-to-br text-white ${meta.gradient}`}>
                        <Icon className="h-3 w-3" />
                      </span>
                      {meta.label}
                    </Link>
                  );
                })}
              </nav>
              <form action="/forum" method="get" role="search" className="flex w-full max-w-md gap-2">
                {category ? <input type="hidden" name="kategori" value={category} /> : null}
                <label htmlFor="forum-ara" className="visually-hidden">
                  Forumda ara
                </label>
                <div className="relative flex-1">
                  <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                  <input
                    id="forum-ara"
                    name="ara"
                    defaultValue={q}
                    maxLength={80}
                    placeholder="Coin, konu, kelime"
                    className="h-10 w-full rounded-xl border border-border bg-surface pl-9 pr-3 text-sm text-fg placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent-text"
                  />
                </div>
                <button type="submit" className="h-10 rounded-xl border border-border bg-surface-2 px-4 text-sm font-semibold text-fg hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent-text">
                  Ara
                </button>
              </form>
            </div>

            {!data.reachable ? (
              <Notice tone="warning" title="Forum şu anda yüklenemedi" role="status">
                Lütfen biraz sonra tekrar deneyin.
              </Notice>
            ) : null}

            {!filtered && overview ? <Board overview={overview} now={now} /> : null}

            <ThreadList title={listTitle} topics={data.items} total={data.total} now={now} empty={<EmptyThreads searching={filtered} />} />

            {data.pages > 1 ? (
              <nav aria-label="Sayfalar" className="flex items-center justify-center gap-3">
                {page > 1 ? (
                  <Link href={href({ kategori: category, ara: q || undefined, sayfa: page - 1 })} className={`${chip} border-border bg-surface text-fg`}>
                    <ChevronLeft aria-hidden="true" className="h-4 w-4" /> Önceki
                  </Link>
                ) : null}
                <span className="text-sm text-muted">
                  Sayfa {data.page} / {data.pages}
                </span>
                {page < data.pages ? (
                  <Link href={href({ kategori: category, ara: q || undefined, sayfa: page + 1 })} className={`${chip} border-border bg-surface text-fg`}>
                    Sonraki <ChevronRight aria-hidden="true" className="h-4 w-4" />
                  </Link>
                ) : null}
              </nav>
            ) : null}
          </div>
          <ForumSidebar overview={overview} now={now} />
        </Container>
      </div>
    </QuotesProvider>
  );
}
