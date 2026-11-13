// Forum mesajı (klasik "postbit" düzeni): üstte tarih ve mesaj numarası şeridi, solda yazar
// sütunu (rütbe sancağı, mesaj sayısı), sağda içerik; altta Faydalı ve Alıntıla.

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
      className={`fb-box ${opener ? "border-accent-text/40" : ""}`}
      data-testid={`post-${index}`}
    >
      <p className="flex items-center justify-between gap-2 border-b border-border bg-surface-3 px-3.5 py-1.5 text-[12px] text-muted">
        <time dateTime={at}>{postDate(at)}</time>
        <span className="flex items-center gap-2">
          {opener ? <span className="rounded bg-accent-text/15 px-1.5 py-px text-[11px] font-semibold text-accent-text">Konuyu açan</span> : null}
          <a href={`#mesaj-${index}`} className="font-mono font-semibold text-fg underline-offset-4 hover:underline">
            #{index}
          </a>
        </span>
      </p>
      <div className="sm:grid sm:grid-cols-[10.5rem_minmax(0,1fr)]">
        <div className="flex items-center gap-3 border-b border-border bg-surface-2 px-3.5 py-3 sm:flex-col sm:items-center sm:border-b-0 sm:border-r sm:px-2 sm:text-center">
          <AuthorAvatar name={author} team={team} />
          <div className="min-w-0">
            {nick ? (
              <Link href={`/forum/uye/${encodeURIComponent(nick)}`} className="block truncate text-[14px] font-bold text-fg underline-offset-4 hover:text-accent-text hover:underline">
                {author}
              </Link>
            ) : (
              <p className="truncate text-[14px] font-bold text-fg">{author}</p>
            )}
            <p className="text-[11.5px] text-muted">Mesaj: {posts}</p>
          </div>
          <div className="ml-auto sm:ml-0 sm:mt-1">
            <AuthorRank posts={posts} team={team} />
          </div>
        </div>
        <div className="flex min-w-0 flex-col">
          <div className="flex-1 px-4 py-3.5">
            <ForumBody body={body} testId={bodyTestId} />
            {children}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-3.5 py-2">
            <LikeButton number={number} replyId={replyId} count={likes} />
            <QuoteButton author={author} body={body} />
          </div>
        </div>
      </div>
    </article>
  );
}
