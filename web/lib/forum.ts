// Forum: herkese açık konu listesi ve konu sayfası (sunucu tarafı). API'ye ulaşılamazsa sayfa
// çökmez; boş liste gösterilir. Gönderiler düz metindir; HTML yorumlanmaz.

import { cache } from "react";

import { runtimeConfig } from "@/lib/config";

export type ForumCategory = "genel" | "strateji" | "soru" | "yeni-coin" | "haber";

export interface TopicSummary {
  number: number;
  title: string;
  category: ForumCategory;
  coin_symbol: string | null;
  author_name: string;
  author_kind: "customer" | "team";
  pinned: boolean;
  locked: boolean;
  source_name: string | null;
  source_url: string | null;
  view_count: number;
  published_at: string;
  reply_count: number;
  last_reply_at: string | null;
  last_reply_author: string | null;
  author_posts?: number;
  excerpt?: string;
}

export interface TopicDetail extends TopicSummary {
  body: string;
  author_posts: number;
  replies: { author_name: string; author_kind: "customer" | "team"; body: string; published_at: string; author_posts: number }[];
}

export interface ForumOverview {
  totals: { topics: number; posts: number; members: number };
  categories: {
    code: ForumCategory;
    label: string;
    topics: number;
    replies: number;
    last: { number: number; title: string; author_name: string; at: string } | null;
  }[];
  trending: { symbol: string; topics: number }[];
  listings: { number: number; title: string; coin_symbol: string | null; author_name: string; published_at: string }[];
}

export async function fetchOverview(): Promise<ForumOverview | null> {
  const cfg = runtimeConfig();
  try {
    const response = await fetch(`${cfg.serverApiUrl}/v1/forum/overview`, { signal: AbortSignal.timeout(3000), cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as ForumOverview;
  } catch {
    return null;
  }
}

/** Mesaj tarihi: "13 Kas 2026 14:05" (İstanbul saati; sunucuda ve tarayıcıda aynı). */
export function postDate(iso: string): string {
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Istanbul" }).format(new Date(iso));
}

export interface TopicList {
  items: TopicSummary[];
  total: number;
  page: number;
  pages: number;
  categories: { code: ForumCategory; label: string; count: number }[];
  reachable: boolean;
}

export const CATEGORY_CODES: ForumCategory[] = ["genel", "strateji", "soru", "yeni-coin", "haber"];

export function isCategory(value: unknown): value is ForumCategory {
  return typeof value === "string" && (CATEGORY_CODES as string[]).includes(value);
}

export async function fetchTopics(params: { category?: ForumCategory; q?: string; page?: number }): Promise<TopicList> {
  const cfg = runtimeConfig();
  const query = new URLSearchParams();
  if (params.category) query.set("category", params.category);
  if (params.q) query.set("q", params.q.slice(0, 80));
  if (params.page && params.page > 1) query.set("page", String(Math.min(params.page, 500)));
  try {
    const response = await fetch(`${cfg.serverApiUrl}/v1/forum/topics?${query}`, {
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(String(response.status));
    return { ...((await response.json()) as Omit<TopicList, "reachable">), reachable: true };
  } catch {
    return { items: [], total: 0, page: 1, pages: 1, categories: [], reachable: false };
  }
}

/** Konu ayrıntısı. Aynı istekte (sayfa başlığı + sayfa) bir kez çekilir: görüntüleme bir artar. */
export const fetchTopic = cache(async (number: number): Promise<TopicDetail | null | "error"> => {
  const cfg = runtimeConfig();
  try {
    const response = await fetch(`${cfg.serverApiUrl}/v1/forum/topics/${number}`, {
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    if (response.status === 404) return null;
    if (!response.ok) return "error";
    return (await response.json()) as TopicDetail;
  } catch {
    return "error";
  }
});

/** "3 dk önce", "2 gün önce"; bir haftadan eskiyse tarih. */
export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return "az önce";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} dk önce`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} sa önce`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} gün önce`;
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium", timeZone: "Europe/Istanbul" }).format(new Date(then));
}

/** Metni paragraflara ayırır (boş satırla). */
export function paragraphs(body: string): string[] {
  return body
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
}
