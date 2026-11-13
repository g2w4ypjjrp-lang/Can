// Forum kenar çubuğu: canlı piyasa, trend coinler, yeni listelemeler, kurallar.

import { Flame, Rocket, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { InlineQuote, MarketBoard } from "@/components/forum/Market";
import { RankLadder } from "@/components/forum/Ranks";
import { CoinToken } from "@/components/forum/Visuals";
import { timeAgo, type ForumOverview } from "@/lib/forum";
import { RANKS } from "@/lib/ranks";

export function ForumSidebar({ overview, now }: { overview: ForumOverview | null; now: number }) {
  return (
    <aside className="space-y-5" aria-label="Forum kenar çubuğu">
      <MarketBoard />
      {overview?.trending.length ? (
        <section aria-labelledby="trend-baslik" className="rounded-2xl border border-border bg-surface p-4">
          <h2 id="trend-baslik" className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Flame aria-hidden="true" className="h-4 w-4 text-down" /> Forumda konuşulan coinler
          </h2>
          <ol className="mt-3 space-y-2">
            {overview.trending.map((t, i) => (
              <li key={t.symbol} className="flex items-center justify-between gap-2">
                <Link href={`/forum?ara=${encodeURIComponent(t.symbol)}`} className="flex items-center gap-2 text-sm underline-offset-4 hover:underline">
                  <span className="w-4 text-xs font-bold text-muted">{i + 1}</span>
                  <CoinToken symbol={t.symbol} size="xs" />
                  <span className="font-semibold text-fg">${t.symbol}</span>
                  <span className="text-xs text-muted">{t.topics} konu</span>
                </Link>
                <InlineQuote symbol={t.symbol} />
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {overview?.listings.length ? (
        <section aria-labelledby="listeleme-baslik" className="rounded-2xl border border-border bg-surface p-4">
          <h2 id="listeleme-baslik" className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Rocket aria-hidden="true" className="h-4 w-4 text-accent-text" /> Yeni listelemeler
          </h2>
          <ul className="mt-3 space-y-3">
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
      <section aria-labelledby="kurallar-baslik" className="rounded-2xl border border-border bg-surface p-4 text-sm">
        <h2 id="kurallar-baslik" className="flex items-center gap-2 font-semibold text-fg">
          <ShieldAlert aria-hidden="true" className="h-4 w-4 text-accent-text" /> Forum kuralları
        </h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
          <li>Her konu ve yanıt ekip onayından sonra yayımlanır.</li>
          <li>Kazanç vaadi, reklam ve yönlendirme bağlantısı yayımlanmaz.</li>
          <li>Kişisel iletişim bilgisi paylaşmayın.</li>
          <li>Paylaşımlar yatırım tavsiyesi değildir; kripto işlemleri kayıpla sonuçlanabilir.</li>
        </ul>
      </section>
      <section aria-labelledby="rutbe-baslik" className="rounded-2xl border border-border bg-surface p-4 text-sm" data-testid="rank-ladder">
        <h2 id="rutbe-baslik" className="flex items-center justify-between font-semibold text-fg">
          Rütbeler
          <Link href="/forum/rutbeler" className="text-xs font-semibold text-accent-text underline-offset-4 hover:underline">
            Rütbe sistemi →
          </Link>
        </h2>
        <p className="mt-1 text-xs text-muted">Yayımlanan mesajlarınızla Seviye 10&apos;dan Seviye 1&apos;e yükselin.</p>
        <div className="mt-3">
          <RankLadder ranks={RANKS} />
        </div>
      </section>
    </aside>
  );
}
