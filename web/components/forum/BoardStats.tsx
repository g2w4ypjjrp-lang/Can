// Forum istatistikleri kutusu (klasik forum düzeni): toplamlar, en yeni üye, en aktif üyeler.

import { BarChart3, Users } from "lucide-react";
import Link from "next/link";

import type { ForumOverview, LeaderEntry } from "@/lib/forum";

export function BoardStats({ overview, leaders }: { overview: ForumOverview; leaders: LeaderEntry[] }) {
  const { topics, posts, members } = overview.totals;
  const link = "font-semibold text-accent-text underline-offset-4 hover:underline";
  return (
    <section aria-labelledby="istatistik" className="fb-box" data-testid="board-stats">
      <h2 id="istatistik" className="fb-thead">
        <BarChart3 aria-hidden="true" className="h-4 w-4" /> Forum istatistikleri
      </h2>
      <div className="fb-row flex gap-3 px-3.5 py-3 text-[13px] text-muted">
        <span aria-hidden="true" className="fb-icon">
          <BarChart3 className="h-4 w-4" />
        </span>
        <p>
          Üyelerimiz toplam <b className="text-fg">{topics}</b> konu ve <b className="text-fg">{posts}</b> mesaj yazdı; son 24 saatte{" "}
          <b className="text-fg">{overview.posts_24h ?? 0}</b> mesaj. Toplam <b className="text-fg">{members}</b> üye.
          {overview.newest_member ? (
            <>
              {" "}
              En yeni üyemiz:{" "}
              <Link href={`/forum/uye/${encodeURIComponent(overview.newest_member)}`} className={link}>
                {overview.newest_member}
              </Link>
              .
            </>
          ) : null}
        </p>
      </div>
      <div className="fb-row flex gap-3 px-3.5 py-3 text-[13px] text-muted">
        <span aria-hidden="true" className="fb-icon">
          <Users className="h-4 w-4" />
        </span>
        <p>
          En aktif üyeler:{" "}
          {leaders.length
            ? leaders.slice(0, 8).map((l, i) => (
                <span key={l.nickname}>
                  {i ? ", " : ""}
                  <Link href={`/forum/uye/${encodeURIComponent(l.nickname)}`} className={link}>
                    {l.nickname}
                  </Link>{" "}
                  ({l.posts})
                </span>
              ))
            : "henüz yok"}
          .{" "}
          <Link href="/forum/rutbeler#liderler" className={link}>
            Liderlik tablosu
          </Link>
        </p>
      </div>
    </section>
  );
}
