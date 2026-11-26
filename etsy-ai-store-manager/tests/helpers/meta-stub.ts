/**
 * TEST DOUBLE of the Meta Graph API v27.0 (read-only Marketing API subset) — tests only.
 * Mirrors the documented contract: GET /act_{id}?fields=…, GET /act_{id}/insights with
 * level=campaign, time_increment=1, time_range JSON, paging.next, error {code} bodies
 * (190 invalid token). Not evidence that the live API behaves identically.
 */
import http from 'node:http';
import type { AddressInfo } from 'node:net';

export const META_TOKEN = 'EAAtest-meta-token-0123456789';
export const META_ACCOUNT = '1234567890';

export interface MetaStub {
  url: string;
  close(): Promise<void>;
  calls: Array<{ path: string; query: Record<string, string> }>;
}

const day = (offset: number) =>
  new Date(Date.now() - offset * 86_400_000).toISOString().slice(0, 10);

export async function startMetaStub(): Promise<MetaStub> {
  const calls: MetaStub['calls'] = [];
  const rows = [0, 1, 2].flatMap((o) => [
    {
      campaign_id: '2385001',
      campaign_name: 'Botanical tees - prospecting',
      date_start: day(o),
      date_stop: day(o),
      spend: '20.00',
      impressions: '5000',
      clicks: '80',
      actions: [
        { action_type: 'link_click', value: '80' },
        { action_type: 'omni_purchase', value: '3' },
      ],
      action_values: [{ action_type: 'omni_purchase', value: '90.00' }],
    },
    {
      campaign_id: '2385002',
      campaign_name: 'Mugs - retargeting',
      date_start: day(o),
      date_stop: day(o),
      spend: '10.00',
      impressions: '2000',
      clicks: '40',
      actions: [{ action_type: 'link_click', value: '40' }],
    },
  ]);
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://x');
    const query = Object.fromEntries(url.searchParams);
    calls.push({ path: url.pathname, query });
    const send = (status: number, body: unknown) => {
      res.writeHead(status, { 'content-type': 'application/json' });
      res.end(JSON.stringify(body));
    };
    if (req.method !== 'GET') return send(400, { error: { code: 100, message: 'GET only' } });
    if (query.access_token !== META_TOKEN)
      return send(401, { error: { code: 190, message: 'Invalid OAuth access token.' } });
    if (url.pathname === `/v27.0/act_${META_ACCOUNT}`)
      return send(200, {
        id: `act_${META_ACCOUNT}`,
        name: 'Botanical Ads',
        currency: 'USD',
        account_status: 1,
      });
    if (url.pathname === `/v27.0/act_${META_ACCOUNT}/insights`) {
      if (!url.searchParams.has('after')) {
        if (query.level !== 'campaign' || query.time_increment !== '1')
          return send(400, {
            error: { code: 100, message: 'expected level=campaign&time_increment=1' },
          });
        const tr = JSON.parse(query.time_range ?? '{}') as { since?: string; until?: string };
        if (!tr.since || !tr.until)
          return send(400, { error: { code: 100, message: 'time_range required' } });
        const next = new URL(
          `http://127.0.0.1:${(server.address() as AddressInfo).port}${url.pathname}`,
        );
        next.searchParams.set('access_token', META_TOKEN);
        next.searchParams.set('after', 'cursor1');
        return send(200, {
          data: rows.slice(0, 3),
          paging: { cursors: { after: 'cursor1' }, next: next.toString() },
        });
      }
      return send(200, { data: rows.slice(3), paging: { cursors: {} } });
    }
    return send(404, { error: { code: 803, message: 'Unknown path' } });
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise((r) => server.close(() => r())),
    calls,
  };
}
