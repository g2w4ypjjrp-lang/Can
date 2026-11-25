import type { Metadata } from 'next';
import Link from 'next/link';
import { CheckCircle2, CircleDashed, AlertTriangle } from 'lucide-react';
import type { DashboardOverview } from '@esm/shared';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatMoney, formatPercent, formatDate } from '@/lib/format';
import { Card, Kpi, Notice, PageHeader } from '@/components/ui';
import { RevenueChart } from '@/components/revenue-chart';
import { CreateStoreForm } from '@/components/create-store-form';

export const metadata: Metadata = { title: 'Genel Bakış' };

const PLATFORM_LABELS: Record<string, string> = {
  etsy: 'Etsy',
  printify: 'Printify',
  etsy_ads: 'Etsy Ads',
  meta_ads: 'Meta / Instagram / Facebook Ads',
  google_ads: 'Google Ads',
  pinterest_ads: 'Pinterest Ads',
  tiktok_ads: 'TikTok Ads',
};

export default async function OverviewPage() {
  const { current } = await loadStores();

  if (!current) {
    return (
      <>
        <PageHeader title="Hoş geldiniz" description="Başlamak için mağaza kaydınızı oluşturun." />
        <Card title="1. Mağaza kaydı">
          <p className="mb-4 text-sm text-slate-600">
            Bu kayıt; ayarlarınızı, kâr politikanızı ve ileride bağlanacak Etsy/Printify hesaplarını
            bir arada tutar. Etsy mağazanızın verileri <strong>FAZ 2</strong>&apos;de resmi OAuth
            bağlantısıyla içeri aktarılacaktır.
          </p>
          <CreateStoreForm />
        </Card>
      </>
    );
  }

  const o = await api<DashboardOverview>(`/stores/${current.id}/dashboard`);
  const c = o.currency;

  return (
    <>
      <PageHeader
        title="Genel Bakış"
        description={`${current.name} · son ${o.dailyRevenue.length} gün`}
      >
        <DataOriginBadge origin={o.dataOrigin} />
      </PageHeader>

      {o.notes.length > 0 && (
        <div className="mb-6 space-y-2">
          {o.notes.map((n) => (
            <Notice key={n} tone={o.dataOrigin === 'demo' ? 'warn' : 'info'}>
              {n}
            </Notice>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" data-testid="kpis">
        <Kpi label="Bugünkü ciro" value={formatMoney(o.kpis.revenueToday, c)} hint="Vergi hariç" />
        <Kpi label="Aylık ciro" value={formatMoney(o.kpis.revenueMonth, c)} />
        <Kpi
          label="Aylık sipariş"
          value={String(o.kpis.ordersMonth)}
          hint={`Ort. sepet: ${formatMoney(o.kpis.averageOrderValue, c)}`}
        />
        <Kpi
          label="Aylık katkı"
          value={formatMoney(o.kpis.contributionMonth, c)}
          hint="Profit Engine (FAZ 4)"
        />
        <Kpi
          label="Reklam harcaması"
          value={formatMoney(o.kpis.adSpendMonth, c)}
          hint="Bu ay, gerçek harcama kaydı"
        />
        <Kpi label="ROAS" value={o.kpis.roas ?? '—'} hint="Ciro / reklam harcaması (atıf değil)" />
        <Kpi label="İade oranı" value={formatPercent(o.kpis.refundRate)} />
        <Kpi
          label="Bekleyen onay"
          value={String(o.pendingApprovals)}
          hint="AI / sistem önerileri"
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Günlük ciro" className="lg:col-span-2">
          <RevenueChart data={o.dailyRevenue} currency={c} />
        </Card>
        <Card title="Entegrasyonlar">
          <ul className="space-y-2.5">
            {o.integrations.map((i) => (
              <li key={i.platform} className="flex items-center justify-between gap-2 text-sm">
                <span className="text-slate-700">{PLATFORM_LABELS[i.platform] ?? i.platform}</span>
                <IntegrationStatus status={i.status} />
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="En çok satanlar">
          {o.topProducts.length === 0 ? (
            <p className="text-sm text-slate-500">Satış kaydı yok.</p>
          ) : (
            <ul className="divide-y divide-line text-sm">
              {o.topProducts.map((p) => (
                <li key={p.title} className="flex justify-between gap-2 py-2">
                  <span className="truncate text-slate-700">{p.title}</span>
                  <span className="shrink-0 tabular-nums text-slate-500">
                    {p.units} · {formatMoney(p.revenue, c)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Ülke bazlı satış">
          {o.countrySales.length === 0 ? (
            <p className="text-sm text-slate-500">Satış kaydı yok.</p>
          ) : (
            <ul className="divide-y divide-line text-sm">
              {o.countrySales.map((x) => (
                <li key={x.country} className="flex justify-between py-2">
                  <span className="text-slate-700">{x.country}</span>
                  <span className="tabular-nums text-slate-500">
                    {x.orders} · {formatMoney(x.revenue, c)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card
          title="AI önerileri"
          action={
            <Link href="/dashboard/ai-manager" className="text-xs text-brand-600 hover:underline">
              Tümü
            </Link>
          }
        >
          {o.recentDecisions.length === 0 ? (
            <p className="text-sm text-slate-500">
              Henüz öneri yok. AI Store Manager, gerçek mağaza verisi bağlandıktan sonra (FAZ 10)
              öneri üretecek.
            </p>
          ) : (
            <ul className="space-y-3 text-sm">
              {o.recentDecisions.map((d) => (
                <li key={d.id}>
                  <p className="text-slate-800">{d.summary}</p>
                  <p className="text-xs text-slate-500">
                    Güven: {d.confidence} · {formatDate(d.createdAt)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function DataOriginBadge({ origin }: { origin: DashboardOverview['dataOrigin'] }) {
  const map = {
    live: ['Canlı veri', 'bg-emerald-100 text-emerald-800'],
    demo: ['DEMO verisi', 'bg-amber-100 text-amber-800'],
    none: ['Veri kaynağı bağlı değil', 'bg-slate-100 text-slate-600'],
  } as const;
  const [label, cls] = map[origin];
  return (
    <span data-testid="data-origin" className={`rounded-full px-3 py-1 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

function IntegrationStatus({ status }: { status: string }) {
  if (status === 'active')
    return (
      <span className="flex items-center gap-1 text-emerald-700">
        <CheckCircle2 className="h-4 w-4" aria-hidden /> Bağlı
      </span>
    );
  if (status === 'not_connected')
    return (
      <span className="flex items-center gap-1 text-slate-400">
        <CircleDashed className="h-4 w-4" aria-hidden /> Bağlı değil
      </span>
    );
  return (
    <span className="flex items-center gap-1 text-amber-700">
      <AlertTriangle className="h-4 w-4" aria-hidden /> {status}
    </span>
  );
}
