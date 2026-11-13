// Konu satırları (klasik forum listesi): konu, yanıt, görüntüleme, son mesaj. Satırın tamamı
// tıklanır (başlık bağlantısı satırı kaplar).

import { Lock, MessagesSquare, Pin, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CATEGORY_META, CategoryChip, CoinToken } from "@/components/forum/Visuals";
import { timeAgo, type TopicSummary } from "@/lib/forum";

export function ThreadList({
  title,
  topics,
  now,
  total,
  empty,
  actions,
}: {
  title: string;
  topics: TopicSummary[];
  now: number;
  total: number;
  empty: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section aria-labelledby="konular-baslik">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="konular-baslik" className="flex items-center gap-2 text-lg font-semibold text-fg">
          <span aria-hidden="true" className="h-5 w-1 rounded-full bg-brand" /> {title}
          <span className="text-sm font-normal text-muted" data-testid="forum-total">
            {total} konu
          </span>
        </h2>
        {actions}
      </div>
      {topics.length === 0 ? (
        empty
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface">
          <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1fr)_4.5rem_5.5rem_11rem] gap-3 border-b border-border bg-surface-2 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted md:grid">
            <span>Konu</span>
            <span className="text-center">Yanıt</span>
            <span className="text-center">Görüntüleme</span>
            <span>Son mesaj</span>
          </div>
          <ul className="divide-y divide-border" aria-label="Konular">
            {topics.map((t) => {
              const meta = CATEGORY_META[t.category];
              const Icon = meta.icon;
              const team = t.author_kind === "team";
              return (
                <li
                  key={t.number}
                  className={`group relative grid gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2 md:grid-cols-[minmax(0,1fr)_4.5rem_5.5rem_11rem] md:items-center ${
                    t.pinned ? "bg-accent-text/[0.06]" : ""
                  }`}
                  data-testid={`topic-${t.number}`}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    {t.coin_symbol ? (
                      <CoinToken symbol={t.coin_symbol} size="sm" />
                    ) : (
                      <span aria-hidden="true" className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-white ${meta.gradient}`}>
                        <Icon className="h-4 w-4" />
                      </span>
                    )}
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        {t.pinned ? (
                          <span className="inline-flex items-center gap-1 rounded-md bg-accent-text/15 px-1.5 py-0.5 text-[11px] font-bold uppercase text-accent-text">
                            <Pin aria-hidden="true" className="h-3 w-3" /> Sabit
                          </span>
                        ) : null}
                        {team ? (
                          <span className="inline-flex items-center gap-1 rounded-md bg-success-bg px-1.5 py-0.5 text-[11px] font-bold uppercase text-success-fg">
                            <ShieldCheck aria-hidden="true" className="h-3 w-3" /> Resmî
                          </span>
                        ) : null}
                        {t.locked ? (
                          <span className="inline-flex text-muted">
                            <Lock aria-hidden="true" className="h-3.5 w-3.5" />
                            <span className="visually-hidden">Yanıtlara kapalı</span>
                          </span>
                        ) : null}
                        <Link
                          href={`/forum/${t.number}`}
                          className="font-semibold text-fg after:absolute after:inset-0 after:content-[''] group-hover:text-accent-text focus-visible:outline-none"
                        >
                          {t.title}
                        </Link>
                      </p>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                        <span className="font-medium text-fg">{t.author_name}</span>
                        <span aria-hidden="true">·</span>
                        <CategoryChip category={t.category} />
                        {t.coin_symbol ? <span className="font-mono font-semibold text-accent-text">${t.coin_symbol}</span> : null}
                        <span aria-hidden="true">·</span>
                        <span>{timeAgo(t.published_at, now)}</span>
                        <span className="md:hidden">
                          · {t.reply_count} yanıt · {t.view_count} görüntüleme
                        </span>
                      </p>
                    </div>
                  </div>
                  <p className="hidden text-center md:block">
                    <span className="font-semibold tabular text-fg">{t.reply_count}</span>
                    <span className="visually-hidden"> yanıt</span>
                  </p>
                  <p className="hidden text-center md:block">
                    <span className="tabular text-muted">{t.view_count}</span>
                    <span className="visually-hidden"> görüntüleme</span>
                  </p>
                  <p className="hidden min-w-0 text-xs md:block">
                    <span className="block text-fg">{timeAgo(t.last_reply_at ?? t.published_at, now)}</span>
                    <span className="block truncate text-muted">{t.last_reply_author ?? t.author_name}</span>
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

export function EmptyThreads({ searching }: { searching: boolean }) {
  return (
    <div className="rounded-2xl border border-dashed border-border bg-surface/60 px-6 py-14 text-center" data-testid="forum-empty">
      <MessagesSquare aria-hidden="true" className="mx-auto h-10 w-10 text-muted" />
      <p className="mt-3 text-lg font-semibold text-fg">{searching ? "Bu aramada konu yok" : "Henüz konu yok"}</p>
      <p className="mt-1 text-sm text-muted">İlk konuyu siz açın; ekibimiz inceledikten sonra burada yayımlanır.</p>
      <Link
        href="/forum/yeni"
        className="mt-6 inline-flex rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-white shadow-glow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text"
      >
        Konu aç
      </Link>
    </div>
  );
}
