/**
 * READ-ONLY Meta Marketing API client (Graph API v27.0, released 2026-11-04).
 * Verified from developers.facebook.com:
 *  - GET /act_{ad_account_id}/insights with level=campaign, time_increment=1 (daily rows),
 *    time_range={"since":"YYYY-MM-DD","until":"YYYY-MM-DD"}, fields spend/impressions/clicks/actions/action_values
 *  - permission ads_read is enough for reporting
 * Budget writes are NOT implemented: the docs do not state the unit of daily_budget, so
 * budget changes go through the approved manual workflow instead.
 */
export const META_GRAPH_VERSION = 'v27.0';
export const META_DEFAULT_BASE = 'https://graph.facebook.com';

/** Purchase action types in priority order (first one present is used; not all are documented). */
export const META_PURCHASE_ACTION_TYPES = [
  'omni_purchase',
  'purchase',
  'offsite_conversion.fb_pixel_purchase',
];

export interface MetaInsightRow {
  campaign_id: string;
  campaign_name: string;
  date_start: string;
  date_stop: string;
  spend?: string;
  impressions?: string;
  clicks?: string;
  actions?: Array<{ action_type: string; value: string }>;
  action_values?: Array<{ action_type: string; value: string }>;
}

export class MetaApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: number | null,
    message: string,
  ) {
    super(message);
    this.name = 'MetaApiError';
  }
  /** 190 invalid token, 200 permissions */
  get isAuthError() {
    return this.code === 190 || this.code === 200 || this.status === 401;
  }
  /** 613 / 80004 rate limits */
  get isRateLimit() {
    return this.code === 613 || this.code === 80004 || this.status === 429;
  }
}

export class MetaAdsClient {
  private readonly base: string;
  constructor(
    private readonly opts: {
      accessToken: string;
      baseUrl?: string | undefined;
      fetchImpl?: typeof fetch;
      sleep?: (ms: number) => Promise<void>;
    },
  ) {
    this.base = `${(opts.baseUrl ?? META_DEFAULT_BASE).replace(/\/+$/, '')}/${META_GRAPH_VERSION}`;
  }

  private async get<T>(path: string, query: Record<string, string>): Promise<T> {
    const url = new URL(path.startsWith('http') ? path : this.base + path);
    for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
    if (!url.searchParams.has('access_token'))
      url.searchParams.set('access_token', this.opts.accessToken);
    const f = this.opts.fetchImpl ?? fetch;
    const sleep = this.opts.sleep ?? ((ms: number) => new Promise((r) => setTimeout(r, ms)));
    for (let attempt = 0; ; attempt++) {
      const res = await f(url, { headers: { Accept: 'application/json' } });
      const text = await res.text();
      if (res.ok) return JSON.parse(text) as T;
      let code: number | null = null;
      let message = text.slice(0, 300);
      try {
        const j = JSON.parse(text) as { error?: { code?: number; message?: string } };
        code = j.error?.code ?? null;
        message = (j.error?.message ?? message).slice(0, 300);
      } catch {
        /* keep raw */
      }
      const err = new MetaApiError(res.status, code, message);
      if ((err.isRateLimit || res.status >= 500) && attempt < 3) {
        await sleep(2000 * 2 ** attempt);
        continue;
      }
      throw err;
    }
  }

  getAdAccount(adAccountId: string) {
    return this.get<{ id: string; name: string; currency: string; account_status: number }>(
      `/act_${encodeURIComponent(adAccountId)}`,
      { fields: 'name,currency,account_status' },
    );
  }

  /** Daily campaign rows; follows paging.next. */
  async *iterateDailyCampaignInsights(adAccountId: string, since: string, until: string) {
    let next: string | null = null;
    let first = true;
    while (first || next) {
      const page: { data: MetaInsightRow[]; paging?: { next?: string } } = first
        ? await this.get(`/act_${encodeURIComponent(adAccountId)}/insights`, {
            level: 'campaign',
            time_increment: '1',
            time_range: JSON.stringify({ since, until }),
            fields: 'campaign_id,campaign_name,spend,impressions,clicks,actions,action_values',
            limit: '500',
          })
        : await this.get(next!, {});
      first = false;
      for (const r of page.data) yield r;
      next = page.paging?.next ?? null;
    }
  }
}

/** Picks the purchase count/value from actions/action_values using the priority list. */
export function metaPurchases(row: MetaInsightRow): {
  conversions: string;
  value: string;
  actionType: string | null;
} {
  for (const t of META_PURCHASE_ACTION_TYPES) {
    const a = row.actions?.find((x) => x.action_type === t);
    if (a) {
      const v = row.action_values?.find((x) => x.action_type === t);
      return { conversions: a.value, value: v?.value ?? '0', actionType: t };
    }
  }
  return { conversions: '0', value: '0', actionType: null };
}
