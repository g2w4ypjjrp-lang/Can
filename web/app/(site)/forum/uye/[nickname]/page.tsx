import type { Metadata } from "next";

import { MessageCircle } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ForumHeader } from "@/components/forum/ForumHeader";
import { RankBanner } from "@/components/forum/Ranks";
import { AuthorAvatar, CategoryChip, CoinToken } from "@/components/forum/Visuals";
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
  const joined = new Intl.DateTimeFormat("tr-TR", { dateStyle: "long", timeZone: "Europe/Istanbul" }).format(new Date(member.joined_at));
  const rows: [string, string | number][] = [
    ["Rütbe", `Seviye ${rank.level} · ${rank.name}`],
    ["Katılım", joined],
    ["Mesaj", member.posts],
    ["Konu", member.topics],
    ["Yanıt", member.replies],
    ["Faydalı", member.likes],
  ];

  return (
    <div className="stage pb-12">
      <ForumHeader
        title={<span data-testid="member-name">{member.nickname}</span>}
        subtitle={`Forum üyesi · Seviye ${rank.level} · ${rank.name}`}
        crumbs={[{ label: "Üyeler" }, { label: member.nickname }]}
      />
      <Container className="fb mt-4 grid gap-4 md:grid-cols-[13rem_minmax(0,1fr)]">
        <section aria-label="Rütbe" className="fb-box">
          <p className="fb-thead">Rütbe</p>
          <div className="space-y-3 p-3">
            <RankBanner rank={rank} current />
            {next ? (
              <div className="text-[12px] text-muted">
                <p>
                  Sonraki: Seviye {next.rank.level} · {next.rank.name}
                </p>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3">
                  <div className={`h-full rounded-full bg-brand ${WIDTHS[Math.round(next.progress * 10)] ?? "w-full"}`} />
                </div>
                <p className="mt-1">{next.remaining} mesaj kaldı</p>
              </div>
            ) : (
              <p className="text-[12px] font-semibold text-accent-text">En üst rütbede 👑</p>
            )}
          </div>
        </section>
        <div className="min-w-0 space-y-4">
          <section aria-labelledby="bilgiler" className="fb-box">
            <h2 id="bilgiler" className="fb-thead">
              <AuthorAvatar name={member.nickname} team={false} size="sm" /> {member.nickname} kullanıcısının bilgileri
            </h2>
            <dl data-testid="member-stats">
              {rows.map(([label, value]) => (
                <div key={label} className="fb-row grid grid-cols-[8rem_minmax(0,1fr)] gap-3 px-3.5 py-2 text-[13px]">
                  <dt className="font-semibold text-muted">{label}</dt>
                  <dd className="text-fg">{value}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section aria-labelledby="son-konular" className="fb-box">
            <h2 id="son-konular" className="fb-thead">
              Son konuları
            </h2>
            {member.recent_topics.length === 0 ? (
              <p className="p-3.5 text-[13px] text-muted">Henüz yayımlanmış konusu yok.</p>
            ) : (
              <ul>
                {member.recent_topics.map((t) => (
                  <li key={t.number} className="fb-row flex items-center gap-3 px-3.5 py-2.5">
                    {t.coin_symbol ? <CoinToken symbol={t.coin_symbol} size="sm" /> : null}
                    <div className="min-w-0 flex-1">
                      <Link href={`/forum/${t.number}`} prefetch={false} className="text-[14px] font-semibold text-fg underline-offset-4 hover:text-accent-text hover:underline">
                        {t.title}
                      </Link>
                      <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[12px] text-muted">
                        <CategoryChip category={t.category} /> {timeAgo(t.published_at, now)}
                      </p>
                    </div>
                    <span className="inline-flex items-center gap-1 text-[12px] text-muted">
                      <MessageCircle aria-hidden="true" className="h-3.5 w-3.5" /> {t.reply_count}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </Container>
    </div>
  );
}
