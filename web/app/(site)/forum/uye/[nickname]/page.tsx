import type { Metadata } from "next";

import { ChevronRight, MessageCircle, MessagesSquare, PenSquare, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { RankBanner } from "@/components/forum/Ranks";
import { AuthorAvatar, CandleBackdrop, CategoryChip, CoinToken } from "@/components/forum/Visuals";
import { Container, Notice } from "@/components/ui";
import { fetchMember, timeAgo } from "@/lib/forum";
import { nextRank, rankFor } from "@/lib/ranks";

type Props = { params: Promise<{ nickname: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const nickname = decodeURIComponent((await params).nickname);
  return { title: `${nickname} · Forum üyesi`, robots: { index: false, follow: true } };
}

const WIDTHS = ["w-[3%]", "w-[10%]", "w-[20%]", "w-[30%]", "w-[40%]", "w-[50%]", "w-[60%]", "w-[70%]", "w-[80%]", "w-[90%]", "w-full"];

export default async function MemberPage({ params }: Props) {
  const nickname = decodeURIComponent((await params).nickname).slice(0, 40);
  const member = await fetchMember(nickname);
  if (member === null) notFound();
  if (member === "error") {
    return (
      <Container className="py-16">
        <h1 className="text-2xl font-semibold text-fg">Forum üyesi</h1>
        <div className="mt-4">
          <Notice tone="warning" title="Profil şu anda yüklenemedi" role="status">
            Lütfen biraz sonra tekrar deneyin.
          </Notice>
        </div>
      </Container>
    );
  }
  const rank = rankFor(member.posts, false);
  const next = nextRank(member.posts, false);
  const now = Date.now();
  const joined = new Intl.DateTimeFormat("tr-TR", { month: "long", year: "numeric", timeZone: "Europe/Istanbul" }).format(new Date(member.joined_at));

  return (
    <div className="stage">
      <header className="relative overflow-hidden border-b border-border">
        <CandleBackdrop className="pointer-events-none absolute inset-0 h-full w-full" />
        <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-r from-bg/90 via-bg/70 to-bg/30" />
        <Container className="relative py-10">
          <nav aria-label="Konum" className="flex items-center gap-1.5 text-sm text-muted">
            <Link href="/forum" className="underline-offset-4 hover:text-fg hover:underline">
              Forum
            </Link>
            <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
            <span className="text-fg">Üye</span>
          </nav>
          <div className="mt-6 grid items-center gap-8 md:grid-cols-[10rem_minmax(0,1fr)]">
            <div className="mx-auto w-40 md:mx-0">
              <RankBanner rank={rank} current />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <AuthorAvatar name={member.nickname} team={false} size="lg" />
                <div className="min-w-0">
                  <h1 className="truncate text-3xl font-bold tracking-tight text-fg sm:text-4xl" data-testid="member-name">
                    {member.nickname}
                  </h1>
                  <p className="text-sm text-muted">
                    Seviye {rank.level} · {rank.name} · {joined} tarihinden beri üye
                  </p>
                </div>
              </div>
              <dl className="mt-6 grid grid-cols-3 gap-3" data-testid="member-stats">
                {[
                  { label: "Mesaj", value: member.posts, icon: MessagesSquare },
                  { label: "Konu", value: member.topics, icon: PenSquare },
                  { label: "Faydalı", value: member.likes, icon: ThumbsUp },
                ].map(({ label, value, icon: Icon }) => (
                  <div key={label} className="neon-card rounded-2xl p-4">
                    <dt className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted">
                      <Icon aria-hidden="true" className="h-3.5 w-3.5" /> {label}
                    </dt>
                    <dd className="mt-1 text-3xl font-bold tabular text-fg">{value}</dd>
                  </div>
                ))}
              </dl>
              {next ? (
                <div className="mt-5 max-w-md">
                  <div className="flex justify-between text-xs text-muted">
                    <span>Sonraki rütbe: Seviye {next.rank.level} · {next.rank.name}</span>
                    <span>{next.remaining} mesaj kaldı</span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-3">
                    <div className={`h-full rounded-full bg-brand ${WIDTHS[Math.round(next.progress * 10)] ?? "w-full"}`} />
                  </div>
                </div>
              ) : (
                <p className="mt-5 text-sm font-semibold text-accent-text">En üst rütbede: Seviye 1 · Bitcoin 👑</p>
              )}
            </div>
          </div>
        </Container>
      </header>
      <Container className="py-10">
        <section aria-labelledby="son-konular">
          <h2 id="son-konular" className="flex items-center gap-2 text-lg font-semibold text-fg">
            <span aria-hidden="true" className="h-5 w-1 rounded-full bg-brand" /> Son konuları
          </h2>
          {member.recent_topics.length === 0 ? (
            <p className="mt-3 text-sm text-muted">Henüz yayımlanmış konusu yok.</p>
          ) : (
            <ul className="mt-4 divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface">
              {member.recent_topics.map((t) => (
                <li key={t.number} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-2">
                  {t.coin_symbol ? <CoinToken symbol={t.coin_symbol} size="sm" /> : null}
                  <div className="min-w-0 flex-1">
                    <Link href={`/forum/${t.number}`} prefetch={false} className="font-semibold text-fg underline-offset-4 hover:text-accent-text hover:underline">
                      {t.title}
                    </Link>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <CategoryChip category={t.category} /> {timeAgo(t.published_at, now)}
                    </p>
                  </div>
                  <span className="inline-flex items-center gap-1 text-xs text-muted">
                    <MessageCircle aria-hidden="true" className="h-3.5 w-3.5" /> {t.reply_count}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </Container>
    </div>
  );
}
