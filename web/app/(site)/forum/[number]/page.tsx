import type { Metadata } from "next";

import { ExternalLink, Eye, Lock, MessageCircle, Pin, ShieldCheck } from "lucide-react";
import { notFound } from "next/navigation";

import { ForumHeader } from "@/components/forum/ForumHeader";
import { SentimentPoll, TopicStateProvider } from "@/components/forum/Interactions";
import { CoinPriceCard, MarketBoard, MarketTicker, QuotesProvider } from "@/components/forum/Market";
import { Post } from "@/components/forum/Post";
import { ReplyForm } from "@/components/forum/ReplyForm";
import { CATEGORY_META, CategoryChip } from "@/components/forum/Visuals";
import { Container, Notice } from "@/components/ui";
import { fetchTopic, postDate } from "@/lib/forum";
import { TICKER_SYMBOLS, fetchQuotes } from "@/lib/market";

type Props = { params: Promise<{ number: string }> };

function parseNumber(value: string): number | null {
  return /^\d{1,15}$/.test(value) ? Number(value) : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const number = parseNumber((await params).number);
  const topic = number ? await fetchTopic(number) : null;
  if (!topic || topic === "error") return { title: "Forum" };
  return { title: `${topic.title} · Forum`, description: topic.body.slice(0, 160) };
}

export default async function TopicPage({ params }: Props) {
  const number = parseNumber((await params).number);
  if (number === null) notFound();
  const topic = await fetchTopic(number);
  if (topic === null) notFound();
  if (topic === "error") {
    return (
      <Container className="py-16">
        <h1 className="text-2xl font-semibold text-fg">Forum</h1>
        <div className="mt-4">
          <Notice tone="warning" title="Konu şu anda yüklenemedi" role="status">
            Lütfen biraz sonra tekrar deneyin.
          </Notice>
        </div>
      </Container>
    );
  }
  const meta = CATEGORY_META[topic.category];
  const team = topic.author_kind === "team";
  const extra = topic.coin_symbol && !TICKER_SYMBOLS.includes(topic.coin_symbol) ? [topic.coin_symbol] : [];
  const quotes = await fetchQuotes([...TICKER_SYMBOLS, ...extra]);

  return (
    <QuotesProvider initial={quotes} extra={extra}>
      <TopicStateProvider number={topic.number}>
        <div className="stage pb-12">
          <MarketTicker />
          <ForumHeader
            title={topic.title}
            subtitle={
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <CategoryChip category={topic.category} />
                {topic.coin_symbol ? <span className="font-mono font-bold text-accent-text">${topic.coin_symbol}</span> : null}
                {topic.pinned ? (
                  <span className="inline-flex items-center gap-1 rounded bg-accent-text/15 px-1.5 py-px text-[11px] font-bold uppercase text-accent-text">
                    <Pin aria-hidden="true" className="h-3 w-3" /> Sabit
                  </span>
                ) : null}
                {team ? (
                  <span className="inline-flex items-center gap-1 rounded bg-success-bg px-1.5 py-px text-[11px] font-bold uppercase text-success-fg">
                    <ShieldCheck aria-hidden="true" className="h-3 w-3" /> Resmî paylaşım
                  </span>
                ) : null}
                {topic.locked ? (
                  <span className="inline-flex items-center gap-1">
                    <Lock aria-hidden="true" className="h-3 w-3" /> Yanıtlara kapalı
                  </span>
                ) : null}
                <span>
                  {topic.author_name} · {postDate(topic.published_at)}
                </span>
                <span className="inline-flex items-center gap-1">
                  <MessageCircle aria-hidden="true" className="h-3.5 w-3.5" /> {topic.reply_count} yanıt
                </span>
                <span className="inline-flex items-center gap-1">
                  <Eye aria-hidden="true" className="h-3.5 w-3.5" /> {topic.view_count} görüntüleme
                </span>
              </span>
            }
            crumbs={[{ href: `/forum?kategori=${topic.category}`, label: meta.label }, { label: topic.title }]}
          />

          <Container className="fb mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_16.5rem]">
            <div className="min-w-0 space-y-3">
              <Post
                index={1}
                number={topic.number}
                author={topic.author_name}
                nick={topic.author_nick}
                team={team}
                posts={topic.author_posts}
                likes={topic.like_count}
                at={topic.published_at}
                body={topic.body}
                opener
                bodyTestId="topic-body"
              >
                {topic.source_url ? (
                  <a
                    href={topic.source_url}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="mt-4 flex items-center justify-between gap-4 rounded-lg border border-border bg-surface-2 px-3.5 py-2.5 hover:border-accent-text/50 focus-visible:outline-2 focus-visible:outline-accent-text"
                    data-testid="topic-source"
                  >
                    <span className="text-[13px]">
                      <span className="block text-[11px] font-semibold uppercase tracking-wider text-muted">Kaynak</span>
                      <span className="block font-semibold text-fg">{topic.source_name ?? "Haber kaynağı"}</span>
                      <span className="block text-[12px] text-muted">Haberin tamamını kaynağında okuyun</span>
                    </span>
                    <ExternalLink aria-hidden="true" className="h-4 w-4 shrink-0 text-accent-text" />
                  </a>
                ) : null}
              </Post>

              {topic.replies.length ? (
                <section aria-label={`Yanıtlar (${topic.replies.length})`} className="space-y-3" data-testid="replies">
                  {topic.replies.map((reply, i) => (
                    <Post
                      key={reply.id}
                      index={i + 2}
                      number={topic.number}
                      replyId={reply.id}
                      author={reply.author_name}
                      nick={reply.author_nick}
                      team={reply.author_kind === "team"}
                      posts={reply.author_posts}
                      likes={reply.like_count}
                      at={reply.published_at}
                      body={reply.body}
                    />
                  ))}
                </section>
              ) : (
                <p className="rounded-xl border border-dashed border-border px-4 py-4 text-center text-[13px] text-muted">
                  Henüz yanıt yok. İlk yanıtı siz yazın.
                </p>
              )}

              {topic.locked ? (
                <Notice tone="info" title="Bu konu yanıtlara kapatıldı">
                  Yeni yanıt yazılamaz.
                </Notice>
              ) : (
                <ReplyForm number={topic.number} />
              )}
            </div>

            <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start" aria-label="Konu kenar çubuğu">
              {topic.coin_symbol ? <CoinPriceCard symbol={topic.coin_symbol} /> : null}
              {topic.coin_symbol && topic.sentiment ? (
                <SentimentPoll number={topic.number} coin={topic.coin_symbol} initial={topic.sentiment} />
              ) : null}
              <MarketBoard limit={6} />
              <section className="fb-box" aria-labelledby="hatirlatma">
                <h2 id="hatirlatma" className="fb-thead">
                  Hatırlatma
                </h2>
                <p className="p-3 text-[12.5px] leading-relaxed text-muted">
                  Forumdaki paylaşımlar yatırım tavsiyesi değildir. Kripto para işlemleri kayıpla sonuçlanabilir; kararlarınızı kendi
                  araştırmanızla verin.
                </p>
              </section>
            </aside>
          </Container>
        </div>
      </TopicStateProvider>
    </QuotesProvider>
  );
}
