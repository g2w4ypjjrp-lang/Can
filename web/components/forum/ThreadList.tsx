// Konu listesi (klasik forum düzeni): önce sabit konular, sonra diğerleri; durum simgesi
// (yeni, popüler, kilitli, sabit), konu, yanıt, görüntüleme ve son mesaj. Satırın tamamı tıklanır.
// Konu bağlantıları önceden yüklenmez: sunucu her konu sayfası çiziminde görüntülemeyi bir artırır.

import { Flame, Lock, MessageSquare, MessagesSquare, Pin, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { RankPill } from "@/components/forum/Ranks";
import { CategoryChip, CoinToken } from "@/components/forum/Visuals";
import { timeAgo, type TopicSummary } from "@/lib/forum";

const DAY_MS = 86_400_000;

function StatusIcon({ topic, now }: { topic: TopicSummary; now: number }) {
  const last = new Date(topic.last_reply_at ?? topic.published_at).getTime();
  const hot = topic.reply_count >= 10 || topic.view_count >= 100;
  const fresh = now - last < DAY_MS;
  const [Icon, cls, label] = topic.locked
    ? [Lock, "", "Kilitli konu"]
    : topic.pinned
      ? [Pin, "fb-icon-new", "Sabit konu"]
      : hot
        ? [Flame, "fb-icon-hot", "Popüler konu"]
        : fresh
          ? [MessageSquare, "fb-icon-new", "Yeni mesaj var"]
          : [MessageSquare, "", "Yeni mesaj yok"];
  return (
    <span className={`fb-icon ${cls}`} title={label}>
      <Icon aria-hidden="true" className="h-4 w-4" />
      <span className="visually-hidden">{label}</span>
    </span>
  );
}

function Row({ t, now }: { t: TopicSummary; now: number }) {
  const team = t.author_kind === "team";
  return (
    <li
      className="fb-row group relative grid gap-2 px-3.5 py-2.5 md:grid-cols-[minmax(0,1fr)_4rem_5.5rem_10.5rem] md:items-center md:gap-3"
      data-testid={`topic-${t.number}`}
    >
      <div className="flex min-w-0 items-center gap-3">
        <StatusIcon topic={t} now={now} />
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[14px] leading-snug">
            {t.pinned ? (
              <span className="rounded bg-accent-text/15 px-1.5 py-px text-[10.5px] font-bold uppercase text-accent-text">Sabit</span>
            ) : null}
            {team ? (
              <span className="inline-flex items-center gap-0.5 rounded bg-success-bg px-1.5 py-px text-[10.5px] font-bold uppercase text-success-fg">
                <ShieldCheck aria-hidden="true" className="h-3 w-3" /> Resmî
              </span>
            ) : null}
            {t.coin_symbol ? (
              <span className="inline-flex items-center gap-1 rounded bg-surface-3 py-px pl-0.5 pr-1.5 font-mono text-[11px] font-bold text-accent-text">
                <CoinToken symbol={t.coin_symbol} size="xs" />${t.coin_symbol}
              </span>
            ) : null}
            <Link
              href={`/forum/${t.number}`}
              prefetch={false}
              className="font-semibold text-fg after:absolute after:inset-0 after:content-[''] group-hover:text-accent-text focus-visible:outline-none"
            >
              {t.title}
            </Link>
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] text-muted">
            <span>Yazar:</span>
            {t.author_nick ? (
              <Link
                href={`/forum/uye/${encodeURIComponent(t.author_nick)}`}
                className="relative z-10 font-medium text-fg underline-offset-4 hover:text-accent-text hover:underline"
              >
                {t.author_name}
              </Link>
            ) : (
              <span className="font-medium text-fg">{t.author_name}</span>
            )}
            {t.author_posts !== undefined ? <RankPill posts={t.author_posts} team={team} /> : null}
            <span aria-hidden="true">·</span>
            <CategoryChip category={t.category} />
            <span aria-hidden="true">·</span>
            <span>{timeAgo(t.published_at, now)}</span>
            <span className="md:hidden">
              · {t.reply_count} yanıt · {t.view_count} görüntüleme
            </span>
          </p>
        </div>
      </div>
      <p className="hidden text-center text-[13px] font-semibold tabular text-fg md:block">
        {t.reply_count}
        <span className="visually-hidden"> yanıt</span>
      </p>
      <p className="hidden text-center text-[13px] tabular text-muted md:block">
        {t.view_count}
        <span className="visually-hidden"> görüntüleme</span>
      </p>
      <p className="hidden min-w-0 text-[12px] leading-snug md:block">
        <span className="block text-fg">{timeAgo(t.last_reply_at ?? t.published_at, now)}</span>
        <span className="block truncate text-muted">Son: {t.last_reply_author ?? t.author_name}</span>
      </p>
    </li>
  );
}

export function ThreadList({
  title,
  topics,
  now,
  total,
  empty,
}: {
  title: string;
  topics: TopicSummary[];
  now: number;
  total: number;
  empty: ReactNode;
}) {
  const pinned = topics.filter((t) => t.pinned);
  const normal = topics.filter((t) => !t.pinned);
  return (
    <section aria-labelledby="konular-baslik" className="fb-box">
      <h2 id="konular-baslik" className="fb-thead">
        <MessagesSquare aria-hidden="true" className="h-4 w-4" /> {title}
        <span className="ml-auto text-[12px] font-normal text-white/90" data-testid="forum-total">
          {total} konu
        </span>
      </h2>
      {topics.length === 0 ? (
        <div className="p-4">{empty}</div>
      ) : (
        <>
          <div aria-hidden="true" className="fb-tcat hidden grid-cols-[minmax(0,1fr)_4rem_5.5rem_10.5rem] gap-3 md:grid">
            <span>Konu</span>
            <span className="text-center">Yanıt</span>
            <span className="text-center">Görüntüleme</span>
            <span>Son mesaj</span>
          </div>
          <ul aria-label="Konular">
            {pinned.length ? (
              <li className="border-b border-border bg-surface-3/60 px-3.5 py-1 text-[11px] font-bold uppercase tracking-wider text-muted">Önemli konular</li>
            ) : null}
            {pinned.map((t) => (
              <Row key={t.number} t={t} now={now} />
            ))}
            {pinned.length && normal.length ? (
              <li className="border-b border-border bg-surface-3/60 px-3.5 py-1 text-[11px] font-bold uppercase tracking-wider text-muted">Konular</li>
            ) : null}
            {normal.map((t) => (
              <Row key={t.number} t={t} now={now} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export function EmptyThreads({ searching }: { searching: boolean }) {
  return (
    <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center" data-testid="forum-empty">
      <MessagesSquare aria-hidden="true" className="mx-auto h-8 w-8 text-muted" />
      <p className="mt-2 text-[15px] font-semibold text-fg">{searching ? "Bu aramada konu yok" : "Henüz konu yok"}</p>
      <p className="mt-1 text-[13px] text-muted">İlk konuyu siz açın; ekibimiz inceledikten sonra burada yayımlanır.</p>
      <Link
        href="/forum/yeni"
        className="mt-4 inline-flex rounded-lg bg-brand px-4 py-2 text-[13px] font-semibold text-white shadow-glow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text"
      >
        Konu aç
      </Link>
    </div>
  );
}

/** Simge açıklamaları (klasik forumlardaki gibi). */
export function Legend() {
  const items: [typeof MessageSquare, string, string][] = [
    [MessageSquare, "fb-icon-new", "Yeni mesaj var"],
    [MessageSquare, "", "Yeni mesaj yok"],
    [Flame, "fb-icon-hot", "Popüler konu"],
    [Pin, "fb-icon-new", "Sabit konu"],
    [Lock, "", "Kilitli konu"],
  ];
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-muted" aria-label="Simge açıklamaları">
      {items.map(([Icon, cls, label]) => (
        <li key={label} className="flex items-center gap-1.5">
          <span aria-hidden="true" className={`fb-icon h-6 w-6 rounded-md ${cls}`}>
            <Icon className="h-3 w-3" />
          </span>
          {label}
        </li>
      ))}
    </ul>
  );
}
