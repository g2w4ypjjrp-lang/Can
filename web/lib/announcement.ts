// Sitenin üstündeki duyuru şeridi (yönetim paneli → Ayarlar → Duyuru şeridi). Kaynak:
// GET /v1/site/announcement. API'ye ulaşılamazsa şerit gösterilmez (site çökmez).

import { runtimeConfig } from "@/lib/config";

export type AnnouncementTone = "info" | "success" | "warning" | "campaign";

export interface SiteAnnouncement {
  text: string;
  link: string;
  tone: AnnouncementTone;
  ends_at: string | null;
}

export interface SiteCampaign {
  percent: number;
  label: string | null;
  ends_at: string | null;
}

export interface AnnouncementState {
  announcement: SiteAnnouncement | null;
  campaign: SiteCampaign | null;
}

const EMPTY: AnnouncementState = { announcement: null, campaign: null };

export async function fetchAnnouncement(fetcher: typeof fetch = fetch): Promise<AnnouncementState> {
  const cfg = runtimeConfig();
  try {
    const response = await fetcher(`${cfg.serverApiUrl}/v1/site/announcement`, {
      signal: AbortSignal.timeout(1500),
      ...(cfg.plansRevalidateS > 0
        ? { next: { revalidate: Math.min(cfg.plansRevalidateS, 30) } }
        : { cache: "no-store" as const }),
    });
    if (!response.ok) return EMPTY;
    const body = (await response.json()) as Partial<AnnouncementState> | null;
    return { announcement: body?.announcement ?? null, campaign: body?.campaign ?? null };
  } catch {
    return EMPTY;
  }
}

/** Bağlantı yalnızca site içi yol ya da https adresi olabilir (sunucu da denetler). */
export function safeLink(link: string): string | null {
  return /^\/[^\s/][^\s]*$|^\/$/.test(link) || /^https:\/\/[^\s]+$/.test(link) ? link : null;
}
