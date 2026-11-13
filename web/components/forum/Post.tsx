// Forum mesajı: solda yazar sütunu (rozet, rütbe, mesaj sayısı), sağda numaralı içerik.

import type { ReactNode } from "react";

import { AuthorRank } from "@/components/forum/Ranks";
import { AuthorAvatar } from "@/components/forum/Visuals";
import { paragraphs, postDate } from "@/lib/forum";

export function Post({
  index,
  author,
  team,
  posts,
  at,
  body,
  opener = false,
  children,
  bodyTestId,
}: {
  index: number;
  author: string;
  team: boolean;
  posts: number;
  at: string;
  body: string;
  opener?: boolean;
  children?: ReactNode;
  bodyTestId?: string;
}) {
  return (
    <article
      id={`mesaj-${index}`}
      aria-label={`Mesaj ${index}, ${author}`}
      className={`overflow-hidden rounded-2xl border bg-surface sm:grid sm:grid-cols-[11rem_minmax(0,1fr)] ${opener ? "border-accent-text/40 shadow-glow" : "border-border"}`}
    >
      <div className="flex items-center gap-3 border-b border-border bg-surface-2 px-4 py-3 sm:flex-col sm:items-center sm:border-b-0 sm:border-r sm:py-5 sm:text-center">
        <span className="sm:hidden">
          <AuthorAvatar name={author} team={team} />
        </span>
        <span className="hidden sm:block">
          <AuthorAvatar name={author} team={team} size="lg" />
        </span>
        <div className="min-w-0 sm:mt-1">
          <p className="truncate font-semibold text-fg">{author}</p>
          <p className="text-xs text-muted">{posts} mesaj</p>
        </div>
        <div className="ml-auto sm:ml-0 sm:mt-2">
          <AuthorRank posts={posts} team={team} />
        </div>
      </div>
      <div className="min-w-0 p-4 sm:p-5">
        <p className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-xs text-muted">
          <time dateTime={at}>{postDate(at)}</time>
          <span className="flex items-center gap-2">
            {opener ? <span className="rounded-md bg-accent-text/15 px-1.5 py-0.5 font-semibold text-accent-text">Konuyu açan</span> : null}
            <a href={`#mesaj-${index}`} className="font-mono font-semibold text-fg underline-offset-4 hover:underline">
              #{index}
            </a>
          </span>
        </p>
        <div className="mt-3 space-y-3 text-[15.5px] leading-relaxed text-fg" data-testid={bodyTestId}>
          {paragraphs(body).map((p, i) => (
            <p key={i} className="whitespace-pre-line break-words">
              {p}
            </p>
          ))}
        </div>
        {children}
      </div>
    </article>
  );
}
