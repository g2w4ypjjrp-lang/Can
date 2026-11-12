// Satıştaki paketler (sunucu tarafı). API'ye ulaşılamazsa sayfa çökmez; "yakında" gösterilir.

import { runtimeConfig } from "@/lib/config";

export interface Plan {
  code: string;
  name: string;
  duration_days: number | null;
  device_limit: number;
  companion_device_limit: number;
  is_trial: boolean;
  price_minor: number;
  currency: string;
  features: Record<string, unknown>;
  // Genel indirim kampanyası (yönetim panelinden): indirimsiz fiyat ve kampanya bilgisi.
  list_price_minor?: number | null;
  campaign_percent?: number | null;
  campaign_label?: string | null;
  campaign_ends_at?: string | null;
}

export interface CampaignInfo {
  percent: number;
  label: string | null;
  endsAt: string | null;
}

/** Satıştaki paketlerden yürürlükteki kampanya (yoksa null). */
export function activeCampaign(plans: Plan[]): CampaignInfo | null {
  const plan = plans.find((p) => p.campaign_percent);
  if (!plan?.campaign_percent) return null;
  return { percent: plan.campaign_percent, label: plan.campaign_label ?? null, endsAt: plan.campaign_ends_at ?? null };
}

export interface PlanGroup {
  key: string;
  durationDays: number | null;
  options: Plan[];
}

export interface PlansResult {
  plans: Plan[];
  reachable: boolean;
}

export async function fetchPlans(fetcher: typeof fetch = fetch): Promise<PlansResult> {
  const cfg = runtimeConfig();
  try {
    const response = await fetcher(`${cfg.serverApiUrl}/v1/plans`, {
      signal: AbortSignal.timeout(3000),
      ...(cfg.plansRevalidateS > 0
        ? { next: { revalidate: cfg.plansRevalidateS } }
        : { cache: "no-store" as const }),
    });
    if (!response.ok) return { plans: [], reachable: false };
    const plans = (await response.json()) as Plan[];
    return { plans: Array.isArray(plans) ? plans : [], reachable: true };
  } catch {
    return { plans: [], reachable: false };
  }
}

/** Paketleri süreye göre gruplar (deneme ayrı); her grupta cihaz sayısına göre sıralı. */
export function groupPlans(plans: Plan[]): { trial: Plan | undefined; groups: PlanGroup[] } {
  const trial = plans.find((p) => p.is_trial);
  const byDuration = new Map<string, PlanGroup>();
  for (const plan of plans) {
    if (plan.is_trial) continue;
    const key = plan.duration_days === null ? "lifetime" : String(plan.duration_days);
    const group = byDuration.get(key) ?? { key, durationDays: plan.duration_days, options: [] };
    group.options.push(plan);
    byDuration.set(key, group);
  }
  const groups = [...byDuration.values()];
  for (const group of groups) group.options.sort((a, b) => a.device_limit - b.device_limit);
  groups.sort((a, b) => (a.durationDays ?? Number.MAX_SAFE_INTEGER) - (b.durationDays ?? Number.MAX_SAFE_INTEGER));
  return { trial, groups };
}
