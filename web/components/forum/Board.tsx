// Forum ana sayfası: gruplanmış bölüm tabloları (klasik forum düzeni). Son 24 saatte mesaj alan
// bölümün simgesi parlar ("yeni mesaj var").

import Link from "next/link";

import { CATEGORY_META } from "@/components/forum/Visuals";
import { timeAgo, type ForumCategory, type ForumOverview } from "@/lib/forum";

const GROUPS: { title: string; hint: string; codes: ForumCategory[] }[] = [
  { title: "Topluluk", hint: "Sohbet, strateji ve yardım", codes: ["genel", "strateji", "soru"] },
  { title: "Kripto piyasası", hint: "Yeni listelemeler ve ekibin seçtiği haberler", codes: ["yeni-coin", "haber"] },
];

const DAY_MS = 86_400_000;

export function Board({ overview, now }: { overview: ForumOverview; now: number }) {
  const byCode = new Map(overview.categories.map((c) => [c.code, c]));
  return (
    <div className="space-y-4">
      {GROUPS.map((group) => (
        <section key={group.title} aria-label={group.title} className="fb-box">
          <h2 className="fb-thead">
            {group.title}
            <span className="ml-1 text-[12px] font-normal text-white/85">— {group.hint}</span>
          </h2>
          <div aria-hidden="true" className="fb-tcat hidden grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_14rem] gap-3 md:grid">
            <span>Forum</span>
            <span className="text-center">Konu</span>
            <span className="text-center">Mesaj</span>
            <span>Son mesaj</span>
          </div>
          <ul>
            {group.codes.map((code) => {
              const c = byCode.get(code);
              if (!c) return null;
              const meta = CATEGORY_META[code];
              const Icon = meta.icon;
              const fresh = c.last ? now - new Date(c.last.at).getTime() < DAY_MS : false;
              return (
                <li
                  key={code}
                  className="fb-row grid gap-2 px-3.5 py-3 md:grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_14rem] md:items-center md:gap-3"
                  data-testid={`board-${code}`}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span
                      className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br text-white ${meta.gradient} ${fresh ? "shadow-glow ring-2 ring-accent-text/50" : "opacity-60 grayscale-[35%]"}`}
                      title={fresh ? "Yeni mesaj var" : "Yeni mesaj yok"}
                    >
                      <Icon aria-hidden="true" className="h-4 w-4" />
                      <span className="visually-hidden">{fresh ? "Yeni mesaj var" : "Yeni mesaj yok"}</span>
                    </span>
                    <div className="min-w-0">
                      <Link href={`/forum?kategori=${code}`} className="text-[14px] font-semibold text-fg underline-offset-4 hover:text-accent-text hover:underline">
                        {meta.label}
                      </Link>
                      <p className="text-[12.5px] leading-snug text-muted">{meta.hint}</p>
                      <p className="text-[12px] text-muted md:hidden">
                        {c.topics} konu · {c.topics + c.replies} mesaj
                      </p>
                    </div>
                  </div>
                  <p className="hidden text-center text-[13px] font-semibold tabular text-fg md:block">
                    {c.topics}
                    <span className="visually-hidden"> konu</span>
                  </p>
                  <p className="hidden text-center text-[13px] font-semibold tabular text-fg md:block">
                    {c.topics + c.replies}
                    <span className="visually-hidden"> mesaj</span>
                  </p>
                  <div className="min-w-0 text-[12.5px] leading-snug">
                    {c.last ? (
                      <>
                        <Link href={`/forum/${c.last.number}`} prefetch={false} className="block truncate font-medium text-fg underline-offset-4 hover:text-accent-text hover:underline">
                          {c.last.title}
                        </Link>
                        <p className="truncate text-[12px] text-muted">
                          {timeAgo(c.last.at, now)} · {c.last.author_name}
                        </p>
                      </>
                    ) : (
                      <p className="text-[12px] text-muted">Henüz mesaj yok</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
