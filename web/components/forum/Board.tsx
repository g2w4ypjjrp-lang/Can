// Forum ana sayfası: klasik forum bölümleri tablosu (bölüm, konu, mesaj, son mesaj).

import Link from "next/link";

import { CATEGORY_META } from "@/components/forum/Visuals";
import { timeAgo, type ForumOverview } from "@/lib/forum";

export function Board({ overview, now }: { overview: ForumOverview; now: number }) {
  return (
    <section aria-labelledby="bolumler-baslik">
      <h2 id="bolumler-baslik" className="mb-3 flex items-center gap-2 text-lg font-semibold text-fg">
        <span aria-hidden="true" className="h-5 w-1 rounded-full bg-brand" /> Forum bölümleri
      </h2>
      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_15rem] gap-3 border-b border-border bg-surface-2 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted md:grid">
          <span>Bölüm</span>
          <span className="text-center">Konu</span>
          <span className="text-center">Mesaj</span>
          <span>Son mesaj</span>
        </div>
        <ul className="divide-y divide-border">
          {overview.categories.map((c) => {
            const meta = CATEGORY_META[c.code];
            const Icon = meta.icon;
            return (
              <li
                key={c.code}
                className="grid gap-3 px-4 py-4 transition-colors hover:bg-surface-2 md:grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_15rem] md:items-center"
                data-testid={`board-${c.code}`}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span aria-hidden="true" className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br text-white shadow-lg ${meta.gradient}`}>
                    <Icon className="h-5 w-5" />
                  </span>
                  <div className="min-w-0">
                    <Link href={`/forum?kategori=${c.code}`} className="font-semibold text-fg underline-offset-4 hover:text-accent-text hover:underline">
                      {meta.label}
                    </Link>
                    <p className="text-sm text-muted">{meta.hint}</p>
                    <p className="mt-1 text-xs text-muted md:hidden">
                      {c.topics} konu · {c.topics + c.replies} mesaj
                    </p>
                  </div>
                </div>
                <p className="hidden text-center md:block">
                  <span className="block font-semibold tabular text-fg">{c.topics}</span>
                  <span className="visually-hidden">konu</span>
                </p>
                <p className="hidden text-center md:block">
                  <span className="block font-semibold tabular text-fg">{c.topics + c.replies}</span>
                  <span className="visually-hidden">mesaj</span>
                </p>
                <div className="min-w-0 text-sm">
                  {c.last ? (
                    <>
                      <Link href={`/forum/${c.last.number}`} className="block truncate font-medium text-fg underline-offset-4 hover:text-accent-text hover:underline">
                        {c.last.title}
                      </Link>
                      <p className="truncate text-xs text-muted">
                        {c.last.author_name} · {timeAgo(c.last.at, now)}
                      </p>
                    </>
                  ) : (
                    <p className="text-xs text-muted">Henüz mesaj yok</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
