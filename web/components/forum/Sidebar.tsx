// Forum kenar çubuğu: canlı piyasa, trend coinler, yeni listelemeler, kurallar.

import { Flame, Rocket, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { InlineQuote, MarketBoard } from "@/components/forum/Market";
import { RankLadder } from "@/components/forum/Ranks";
import { CoinToken } from "@/components/forum/Visuals";
import { Leaderboard } from "@/components/forum/Leaderboard";
import { timeAgo, type ForumOverview, type LeaderEntry } from "@/lib/forum";
import { RANKS } from "@/lib/ranks";

export function ForumSidebar({ overview, now, leaders = [] }: { overview: ForumOverview | null; now: number; leaders?: LeaderEntry[] }) {
  return (
    <aside className="space-y-4" aria-label="Forum kenar çubuğu">
      <MarketBoard />
      {overview?.trending.length ? (
        <section aria-labelledby="trend-baslik" className="fb-box">
          <h2 id="trend-baslik" className="fb-thead">
            <Flame aria-hidden="true" className="h-4 w-4" /> Forumda konuşulan coinler
          </h2>
          <ol className="space-y-2 p-3 text-[13px]">
            {overview.trending.map((t, i) => (
              <li key={t.symbol} className="flex items-center justify-between gap-2">
                <Link href={`/forum?ara=${encodeURIComponent(t.symbol)}`} className="flex min-w-0 items-center gap-2 underline-offset-4 hover:underline">
                  <span className="w-3 text-[11px] font-bold text-muted">{i + 1}</span>
                  <CoinToken symbol={t.symbol} size="xs" />
                  <span className="min-w-0">
                    <span className="block font-semibold leading-tight text-fg">${t.symbol}</span>
                    <span className="block text-[11px] leading-tight text-muted">{t.topics} konu</span>
                  </span>
                </Link>
                <InlineQuote symbol={t.symbol} />
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {overview?.listings.length ? (
        <section aria-labelledby="listeleme-baslik" className="fb-box">
          <h2 id="listeleme-baslik" className="fb-thead">
            <Rocket aria-hidden="true" className="h-4 w-4" /> Yeni listelemeler
          </h2>
          <ul className="space-y-3 p-3">
            {overview.listings.map((l) => (
              <li key={l.number} className="flex gap-2.5">
                {l.coin_symbol ? <CoinToken symbol={l.coin_symbol} size="sm" /> : null}
                <div className="min-w-0">
                  <Link href={`/forum/${l.number}`} prefetch={false} className="line-clamp-2 text-sm font-medium text-fg underline-offset-4 hover:underline">
                    {l.title}
                  </Link>
                  <p className="text-xs text-muted">{timeAgo(l.published_at, now)}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {leaders.length ? (
        <section aria-labelledby="aktif-baslik" className="fb-box">
          <h2 id="aktif-baslik" className="fb-thead justify-between">
            En aktif üyeler
            <Link href="/forum/rutbeler#liderler" className="text-[12px] font-semibold underline underline-offset-4">
              Tümü →
            </Link>
          </h2>
          <div className="p-3">
            <Leaderboard entries={leaders.slice(0, 5)} compact />
          </div>
        </section>
      ) : null}
      <section aria-labelledby="kurallar-baslik" className="fb-box">
        <h2 id="kurallar-baslik" className="fb-thead">
          <ShieldAlert aria-hidden="true" className="h-4 w-4" /> Forum kuralları
        </h2>
        <ul className="list-disc space-y-1 p-3 pl-7 text-[12.5px] text-muted">
          <li>Her konu ve yanıt ekip onayından sonra yayımlanır.</li>
          <li>Kazanç vaadi, reklam ve yönlendirme bağlantısı yayımlanmaz.</li>
          <li>Kişisel iletişim bilgisi paylaşmayın.</li>
          <li>Paylaşımlar yatırım tavsiyesi değildir; kripto işlemleri kayıpla sonuçlanabilir.</li>
        </ul>
      </section>
      <section aria-labelledby="rutbe-baslik" className="fb-box" data-testid="rank-ladder">
        <h2 id="rutbe-baslik" className="fb-thead justify-between">
          Rütbeler
          <Link href="/forum/rutbeler" className="text-[12px] font-semibold underline underline-offset-4">
            Rütbe sistemi →
          </Link>
        </h2>
        <div className="p-3">
          <p className="mb-2 text-[12px] text-muted">Yayımlanan mesajlarınızla Seviye 10&apos;dan Seviye 1&apos;e yükselin.</p>
          <RankLadder ranks={RANKS} />
        </div>
      </section>
    </aside>
  );
}
