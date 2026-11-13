// Liderlik tablosu: en çok yayımlanmış mesajı olan üyeler (eşitlikte beğeni).

import { Crown, ThumbsUp } from "lucide-react";
import Link from "next/link";

import { RankPill } from "@/components/forum/Ranks";
import type { LeaderEntry } from "@/lib/forum";

export function Leaderboard({ entries, compact = false }: { entries: LeaderEntry[]; compact?: boolean }) {
  if (!entries.length) return <p className="text-sm text-muted">Henüz sıralama yok; ilk mesajlarla dolacak.</p>;
  return (
    <ol className={compact ? "space-y-2" : ""} data-testid="leaderboard">
      {entries.map((e, i) => (
        <li key={e.nickname} className={`flex items-center gap-3 text-[13px] ${compact ? "" : "fb-row px-3.5 py-2.5"}`}>
          <span
            className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-black ${
              i === 0 ? "bg-[#fbbf24] text-[#422006]" : i === 1 ? "bg-[#cbd5e1] text-[#0f172a]" : i === 2 ? "bg-[#d97706] text-[#1c1917]" : "bg-surface-3 text-fg"
            }`}
          >
            {i === 0 ? <Crown aria-hidden="true" className="h-3.5 w-3.5" /> : i + 1}
            {i === 0 ? <span className="visually-hidden">1</span> : null}
          </span>
          <div className="min-w-0 flex-1">
            <Link href={`/forum/uye/${encodeURIComponent(e.nickname)}`} className="truncate font-semibold text-fg underline-offset-4 hover:text-accent-text hover:underline">
              {e.nickname}
            </Link>
            {compact ? null : (
              <span className="ml-2">
                <RankPill posts={e.posts} team={false} />
              </span>
            )}
          </div>
          <span className="tabular text-xs text-muted">{e.posts} mesaj</span>
          {compact ? null : (
            <span className="inline-flex w-14 items-center justify-end gap-1 text-xs text-muted">
              <ThumbsUp aria-hidden="true" className="h-3 w-3" /> {e.likes}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
