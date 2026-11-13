import type { Metadata } from "next";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { Board } from "@/components/forum/Board";
import { BoardStats } from "@/components/forum/BoardStats";
import { ForumHeader } from "@/components/forum/ForumHeader";
import { MarketTicker, QuotesProvider } from "@/components/forum/Market";
import { ForumSidebar } from "@/components/forum/Sidebar";
import { EmptyThreads, Legend, ThreadList } from "@/components/forum/ThreadList";
import { CATEGORY_META } from "@/components/forum/Visuals";
import { Container, Notice } from "@/components/ui";
import { firstParam } from "@/lib/format";
import { fetchLeaderboard, fetchOverview, fetchTopics, isCategory, type ForumCategory } from "@/lib/forum";
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

const pageLink =
  "inline-flex items-center gap-1 rounded-lg border border-border bg-surface px-3 py-1.5 text-[13px] font-semibold text-fg hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-text";

export default async function ForumPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const rawCategory = firstParam(params.kategori);
  const category: ForumCategory | undefined = isCategory(rawCategory) ? rawCategory : undefined;
  const q = (firstParam(params.ara) ?? "").trim().slice(0, 80);
  const page = Math.max(1, Math.min(500, Number(firstParam(params.sayfa)) || 1));
  const [data, overview, quotes, leaders] = await Promise.all([
    fetchTopics({ category, q, page }),
    fetchOverview(),
    fetchQuotes(),
    fetchLeaderboard(),
  ]);
  const filtered = Boolean(category || q);
  // Göreli zamanlar sunucuda bir kez hesaplanır.
  const now = Date.now();
  const listTitle = category ? CATEGORY_META[category].label : q ? `“${q}” araması` : "Son konular";
  const crumbs = category ? [{ label: CATEGORY_META[category].label }] : q ? [{ label: `Arama: ${q}` }] : [];

  return (
    <QuotesProvider initial={quotes}>
      <div className="stage pb-12">
        <MarketTicker />
        <ForumHeader
          title={category ? CATEGORY_META[category].label : "Kripto Forum"}
          subtitle={category ? CATEGORY_META[category].hint : "Yeni coinler, strateji, sorular ve güncel haberler · her konu ekip onayıyla yayımlanır"}
          active={category === "yeni-coin" ? "yeni-coin" : category ? undefined : "home"}
          crumbs={crumbs}
          search={{ category, q }}
        />
        <Container className="fb mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_16.5rem]">
          <div className="min-w-0 space-y-4">
            {!data.reachable ? (
              <Notice tone="warning" title="Forum şu anda yüklenemedi" role="status">
                Lütfen biraz sonra tekrar deneyin.
              </Notice>
            ) : null}

            {!filtered && overview ? <Board overview={overview} now={now} /> : null}

            <ThreadList title={listTitle} topics={data.items} total={data.total} now={now} empty={<EmptyThreads searching={filtered} />} />

            {data.pages > 1 ? (
              <nav aria-label="Sayfalar" className="flex items-center justify-end gap-2">
                {page > 1 ? (
                  <Link href={href({ kategori: category, ara: q || undefined, sayfa: page - 1 })} className={pageLink}>
                    <ChevronLeft aria-hidden="true" className="h-3.5 w-3.5" /> Önceki
                  </Link>
                ) : null}
                <span className="text-[13px] text-muted">
                  Sayfa {data.page} / {data.pages}
                </span>
                {page < data.pages ? (
                  <Link href={href({ kategori: category, ara: q || undefined, sayfa: page + 1 })} className={pageLink}>
                    Sonraki <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
                  </Link>
                ) : null}
              </nav>
            ) : null}

            {!filtered && overview ? <BoardStats overview={overview} leaders={leaders} /> : null}
            <Legend />
          </div>
          <ForumSidebar overview={overview} now={now} />
        </Container>
      </div>
    </QuotesProvider>
  );
}
