import type { Metadata } from "next";

import { ForumHeader } from "@/components/forum/ForumHeader";
import { MarketTicker, QuotesProvider } from "@/components/forum/Market";
import { NewTopic } from "@/components/forum/NewTopic";
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
      <div className="stage pb-12">
        <MarketTicker />
        <ForumHeader
          title="Yeni konu"
          subtitle="Sorunuzu, stratejinizi ya da dikkatinizi çeken yeni bir coini paylaşın; konunuz ekip onayından sonra yayımlanır."
          active="new"
          crumbs={[{ label: "Konu aç" }]}
        />
        <Container className="fb mt-4">
          <NewTopic />
        </Container>
      </div>
    </QuotesProvider>
  );
}
