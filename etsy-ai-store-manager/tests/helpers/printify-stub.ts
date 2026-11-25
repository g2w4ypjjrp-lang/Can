/**
 * TEST DOUBLE of the Printify API v1 (developers.printify.com) — tests only.
 * Enforces Bearer token + User-Agent, cents money, products page size 50,
 * publish.json, webhooks.json. Not evidence of live behaviour.
 */
import http from 'node:http';
import type { AddressInfo } from 'node:net';

export const PRINTIFY_TOKEN = 'printify-test-token';
export const PRINTIFY_SHOP_ID = 7001;

export interface PrintifyStub {
  url: string;
  close(): Promise<void>;
  calls: Array<{ method: string; path: string; status: number }>;
  products: Map<string, Record<string, unknown> & { variants: Array<Record<string, unknown>> }>;
  orders: Array<Record<string, unknown>>;
  published: string[];
  webhooks: Array<{ id: string; topic: string; url: string }>;
}

export async function startPrintifyStub(opts: { port?: number } = {}): Promise<PrintifyStub> {
  const calls: PrintifyStub['calls'] = [];
  const published: string[] = [];
  const webhooks: PrintifyStub['webhooks'] = [];
  const now = new Date().toISOString();
  const products = new Map<
    string,
    Record<string, unknown> & { variants: Array<Record<string, unknown>> }
  >();
  products.set('5d39b159e7c48c000728c89f', {
    id: '5d39b159e7c48c000728c89f',
    title: 'Custom Mug 11oz',
    description: 'Mug',
    tags: ['mug'],
    variants: [
      {
        id: 33719,
        sku: 'MUG-11-W',
        cost: 516,
        price: 1999,
        title: '11oz',
        is_enabled: true,
        is_available: true,
        options: [1],
      },
      {
        id: 33720,
        sku: 'MUG-15-W',
        cost: 650,
        price: 2299,
        title: '15oz',
        is_enabled: true,
        is_available: true,
        options: [2],
      },
    ],
    images: [
      {
        src: 'https://images.printify.com/mock/1.png',
        variant_ids: [33719],
        position: 'front',
        is_default: true,
      },
    ],
    created_at: now,
    updated_at: now,
    visible: true,
    is_locked: false,
    blueprint_id: 68,
    print_provider_id: 1,
    external: { id: '900002', handle: 'https://www.etsy.com/listing/900002' },
    shop_id: PRINTIFY_SHOP_ID,
  });
  products.set('6e4ac260f8d59d000839d9a0', {
    id: '6e4ac260f8d59d000839d9a0',
    title: 'Retro Sunset Tee',
    description: 'Tee',
    tags: ['tee'],
    variants: [
      {
        id: 12100,
        sku: 'TEE-M-BLK',
        cost: 1085,
        price: 2800,
        title: 'Black / M',
        is_enabled: true,
        is_available: true,
        options: [3],
      },
    ],
    images: [],
    created_at: now,
    updated_at: now,
    visible: true,
    is_locked: false,
    blueprint_id: 6,
    print_provider_id: 29,
    external: null,
    shop_id: PRINTIFY_SHOP_ID,
  });
  const orders: Array<Record<string, unknown>> = [
    {
      id: '5a96f649b2439217d070f507',
      status: 'fulfilled',
      shipping_method: 1,
      total_price: 3998,
      total_shipping: 649,
      total_tax: 0,
      metadata: { order_type: 'external', shop_order_id: 1002, shop_order_label: '1002' },
      line_items: [
        {
          id: 'li-1',
          product_id: '5d39b159e7c48c000728c89f',
          variant_id: 33719,
          quantity: 2,
          cost: 1032,
          shipping_cost: 649,
          status: 'fulfilled',
          metadata: { sku: 'MUG-11-W' },
        },
      ],
      shipments: [
        {
          carrier: 'usps',
          number: '9400PRINTIFY',
          url: 'https://track.example/9400PRINTIFY',
          delivered_at: null,
        },
      ],
      created_at: now,
      sent_to_production_at: now,
      fulfilled_at: now,
    },
    {
      id: '5a96f649b2439217d070f508',
      status: 'has-issues',
      shipping_method: 1,
      total_price: 2800,
      total_shipping: 475,
      total_tax: 0,
      metadata: { order_type: 'external', shop_order_id: 999999 },
      line_items: [],
      shipments: [],
      created_at: now,
    },
  ];

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://stub');
    let raw = '';
    for await (const c of req) raw += c;
    const send = (status: number, body: unknown) => {
      calls.push({ method: req.method ?? '', path: url.pathname, status });
      res.writeHead(status, { 'content-type': 'application/json' });
      res.end(JSON.stringify(body));
    };
    if (url.pathname === '/__test/published') return send(200, published);
    if (req.headers.authorization !== `Bearer ${PRINTIFY_TOKEN}`)
      return send(401, { error: 'Unauthenticated' });
    if (!req.headers['user-agent']) return send(400, { error: 'User-Agent required' });
    const p = url.pathname;
    const shopBase = `/v1/shops/${PRINTIFY_SHOP_ID}`;

    if (req.method === 'GET' && p === '/v1/shops.json') {
      return send(200, [
        { id: PRINTIFY_SHOP_ID, title: 'My Etsy via Printify', sales_channel: 'etsy' },
        { id: 7002, title: 'API store', sales_channel: 'custom_integration' },
      ]);
    }
    if (req.method === 'GET' && p === '/v1/catalog/blueprints.json') {
      return send(200, [
        {
          id: 6,
          title: 'Unisex Heavy Cotton Tee',
          description: '',
          brand: 'Gildan',
          model: '5000',
          images: ['https://img/6.png'],
        },
        {
          id: 68,
          title: 'Mug 11oz',
          description: '',
          brand: 'Generic',
          model: 'Mug',
          images: ['https://img/68.png'],
        },
        {
          id: 384,
          title: 'Canvas Gallery Wraps',
          description: '',
          brand: 'Generic',
          model: 'Canvas',
          images: [],
        },
      ]);
    }
    let m = p.match(/^\/v1\/catalog\/blueprints\/(\d+)\.json$/);
    if (req.method === 'GET' && m)
      return send(200, {
        id: Number(m[1]),
        title: Number(m[1]) === 68 ? 'Mug 11oz' : 'Unisex Heavy Cotton Tee',
        description: '',
        brand: 'x',
        model: 'y',
        images: [],
      });
    m = p.match(/^\/v1\/catalog\/blueprints\/(\d+)\/print_providers\.json$/);
    if (req.method === 'GET' && m) {
      return send(200, [
        {
          id: 1,
          title: 'SPOKE Custom Products',
          production_time: { average: 3, unit: 'business_days' },
        },
        {
          id: 29,
          title: 'Monster Digital',
          production_time: { average: 2, unit: 'business_days' },
        },
      ]);
    }
    m = p.match(/^\/v1\/catalog\/print_providers\/(\d+)\.json$/);
    if (req.method === 'GET' && m)
      return send(200, {
        id: Number(m[1]),
        title: 'Provider',
        location: { country: Number(m[1]) === 1 ? 'US' : 'DE' },
      });
    m = p.match(/^\/v1\/catalog\/blueprints\/(\d+)\/print_providers\/(\d+)\/variants\.json$/);
    if (req.method === 'GET' && m) {
      return send(200, {
        id: Number(m[2]),
        title: 'Provider',
        variants: [
          {
            id: 33719,
            title: '11oz',
            options: { size: '11oz' },
            placeholders: [{ position: 'front', width: 2700, height: 1200 }],
          },
          {
            id: 33720,
            title: '15oz',
            options: { size: '15oz' },
            placeholders: [{ position: 'front', width: 2700, height: 1200 }],
          },
          {
            id: 12100,
            title: 'Black / M',
            options: { color: 'Black', size: 'M' },
            placeholders: [{ position: 'front', width: 4500, height: 5400 }],
          },
        ],
      });
    }
    m = p.match(/^\/v1\/catalog\/blueprints\/(\d+)\/print_providers\/(\d+)\/shipping\.json$/);
    if (req.method === 'GET' && m) {
      const pp = Number(m[2]);
      return send(200, {
        handling_time: { value: pp === 1 ? 3 : 2, unit: 'day' },
        profiles: [
          {
            variant_ids: [33719, 33720, 12100],
            first_item: { cost: pp === 1 ? 649 : 475, currency: 'USD' },
            additional_items: { cost: 349, currency: 'USD' },
            countries: ['US'],
          },
          {
            variant_ids: [33719, 33720, 12100],
            first_item: { cost: 1099, currency: 'USD' },
            additional_items: { cost: 599, currency: 'USD' },
            countries: ['DE', 'FR'],
          },
          {
            variant_ids: [33719, 33720, 12100],
            first_item: { cost: 1499, currency: 'USD' },
            additional_items: { cost: 799, currency: 'USD' },
            countries: ['REST_OF_THE_WORLD'],
          },
        ],
      });
    }
    if (req.method === 'GET' && p === `${shopBase}/products.json`) {
      const limit = Number(url.searchParams.get('limit') ?? 10);
      if (limit > 50) return send(400, { error: 'limit max 50' });
      const page = Number(url.searchParams.get('page') ?? 1);
      const all = [...products.values()];
      return send(200, {
        current_page: page,
        last_page: Math.max(1, Math.ceil(all.length / limit)),
        data: all.slice((page - 1) * limit, page * limit),
        total: all.length,
      });
    }
    m = p.match(new RegExp(`^${shopBase}/products/([0-9a-f]{24})\\.json$`));
    if (req.method === 'GET' && m)
      return products.has(m[1]!)
        ? send(200, products.get(m[1]!))
        : send(404, { error: 'not found' });
    m = p.match(new RegExp(`^${shopBase}/products/([0-9a-f]{24})/publish\\.json$`));
    if (req.method === 'POST' && m) {
      const prod = products.get(m[1]!);
      if (!prod) return send(404, { error: 'not found' });
      published.push(m[1]!);
      prod.is_locked = true;
      return send(200, {});
    }
    if (req.method === 'GET' && p === `${shopBase}/orders.json`) {
      return send(200, { current_page: 1, last_page: 1, data: orders });
    }
    if (req.method === 'POST' && p === `${shopBase}/webhooks.json`) {
      const b = JSON.parse(raw) as { topic: string; url: string };
      const w = { id: `wh${webhooks.length + 1}`, topic: b.topic, url: b.url };
      webhooks.push(w);
      return send(200, { ...w, shop_id: PRINTIFY_SHOP_ID });
    }
    send(404, { error: 'not found' });
  });
  await new Promise<void>((r) => server.listen(opts.port ?? 0, '127.0.0.1', r));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise((r) => server.close(() => r())),
    calls,
    products,
    orders,
    published,
    webhooks,
  };
}
