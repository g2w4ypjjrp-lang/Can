import type { Metadata } from "next";

import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { NewTopic } from "@/components/forum/NewTopic";
import { MarketTicker, QuotesProvider } from "@/components/forum/Market";
import { CandleBackdrop } from "@/components/forum/Visuals";
import { Container } from "@/components/ui";
import { fetchQuotes } from "@/lib/market";

export const metadata: Metadata = {
  title: "Konu aç · Forum",
  description: "Foruma yeni konu açın; ekip onayından sonra yayımlanır.",
  robots: { index: false, follow: true },
};

export default async function NewTopicPage() {
  const quotes = await fetchQuotes();
  return (
    <QuotesProvider initial={quotes}>
      <div className="stage">
        <MarketTicker />
        <header className="relative overflow-hidden border-b border-border">
          <CandleBackdrop className="pointer-events-none absolute inset-0 h-full w-full" />
          <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-r from-bg/90 via-bg/60 to-transparent" />
          <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(60%_80%_at_15%_0%,rgba(79,120,255,0.25),transparent_60%)]" />
          <Container className="relative py-10 sm:py-12">
            <nav aria-label="Konum" className="flex items-center gap-1.5 text-sm text-muted">
              <Link href="/forum" className="underline-offset-4 hover:text-fg hover:underline">
                Forum
              </Link>
              <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
              <span className="text-fg">Konu aç</span>
            </nav>
            <h1 className="mt-4 text-3xl font-bold tracking-tight text-fg sm:text-5xl">
              Yeni <span className="text-gradient">konu</span>
            </h1>
            <p className="mt-3 max-w-2xl text-muted">
              Sorunuzu, stratejinizi ya da dikkatinizi çeken yeni bir coini paylaşın. Konunuz ekip onayından sonra forumda yayımlanır.
            </p>
          </Container>
        </header>
        <Container className="py-10">
          <NewTopic />
        </Container>
      </div>
    </QuotesProvider>
  );
}
