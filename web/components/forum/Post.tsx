// Forum mesajı: solda yazar sütunu (rütbe sancağı, mesaj sayısı), sağda numaralı içerik ve
// etkileşimler (Faydalı, Alıntıla). Yazar adı üye profiline bağlanır.

import Link from "next/link";
import type { ReactNode } from "react";

import { ForumBody } from "@/components/forum/Body";
import { LikeButton, QuoteButton } from "@/components/forum/Interactions";
import { AuthorRank } from "@/components/forum/Ranks";
import { AuthorAvatar } from "@/components/forum/Visuals";
import { postDate } from "@/lib/forum";

export function Post({
  index,
  number,
  replyId,
  author,
  nick,
  team,
  posts,
  likes,
  at,
  body,
  opener = false,
  children,
  bodyTestId,
}: {
  index: number;
  number: number;
  replyId?: string;
  author: string;
  nick?: string | null;
  team: boolean;
  posts: number;
  likes: number;
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
      data-testid={`post-${index}`}
    >
      <div className="flex items-center gap-3 border-b border-border bg-surface-2 px-4 py-3 sm:flex-col sm:items-center sm:border-b-0 sm:border-r sm:py-5 sm:text-center">
        <span className="sm:hidden">
          <AuthorAvatar name={author} team={team} />
        </span>
        <span className="hidden sm:block">
          <AuthorAvatar name={author} team={team} size="lg" />
        </span>
        <div className="min-w-0 sm:mt-1">
          {nick ? (
            <Link href={`/forum/uye/${encodeURIComponent(nick)}`} className="block truncate font-semibold text-fg underline-offset-4 hover:text-accent-text hover:underline">
              {author}
            </Link>
          ) : (
            <p className="truncate font-semibold text-fg">{author}</p>
          )}
          <p className="text-xs text-muted">{posts} mesaj</p>
        </div>
        <div className="ml-auto sm:ml-0 sm:mt-2">
          <AuthorRank posts={posts} team={team} />
        </div>
      </div>
      <div className="flex min-w-0 flex-col p-4 sm:p-5">
        <p className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-xs text-muted">
          <time dateTime={at}>{postDate(at)}</time>
          <span className="flex items-center gap-2">
            {opener ? <span className="rounded-md bg-accent-text/15 px-1.5 py-0.5 font-semibold text-accent-text">Konuyu açan</span> : null}
            <a href={`#mesaj-${index}`} className="font-mono font-semibold text-fg underline-offset-4 hover:underline">
              #{index}
            </a>
          </span>
        </p>
        <div className="mt-3 flex-1">
          <ForumBody body={body} testId={bodyTestId} />
          {children}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <LikeButton number={number} replyId={replyId} count={likes} />
          <QuoteButton author={author} body={body} />
        </div>
      </div>
    </article>
  );
}
