import Link from "next/link";
import { Card, Muted } from "@/components/Card";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";
import { formatMoney, metricText, STATUS_TEXT, type Metric, type Money } from "@/lib/format";

type Dashboard = {
  integrations: Record<"youtube" | "etsy" | "printify", string>;
  youtube: { total_views: Metric<number>; subscribers: Metric<number>; estimated_revenue_30d: Metric<Money[]> };
  etsy: { orders_30d: Metric<number>; sales_revenue_30d: Metric<Money[]>;
          net_profit: Metric<{ currency: string; amount: string | null }> };
  expenses_30d: Metric<Money[]>;
  operations: { pending_approvals: number; agents: number; working_agents: number; active_tasks: number; failed_tasks: number };
  recent_completed_tasks: { id: string; title: string; completed_at: string | null }[];
};

function Num({ m }: { m: Metric<number> }) {
  return m.status === "ok" ? <>{metricText(m)}</> : <Muted>{metricText(m)}</Muted>;
}
function Cash({ m }: { m: Metric<Money[]> }) {
  if (m.status !== "ok" || !m.value) return <Muted>{STATUS_TEXT[m.status]}</Muted>;
  return <>{formatMoney(m.value).map((t) => <div key={t}>{t}</div>)}</>;
}

export default async function DashboardPage() {
  const { token, org } = await appContext();
  const d = await api<Dashboard>(`/api/organizations/${org.id}/dashboard`, token);
  const np = d.etsy.net_profit;
  const notConnected = (Object.entries(d.integrations) as [string, string][]).filter(([, s]) => s !== "connected");

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="text-sm text-muted">Son 30 gün. Veri olmayan alanlarda sayı gösterilmez.</p>
      </header>

      {notConnected.length > 0 && (
        <div className="rounded-xl border border-line bg-panel p-4 text-sm">
          Bağlı olmayan hesaplar: <b>{notConnected.map(([p]) => p).join(", ")}</b>. Bağlantılar Phase 3-4 ile
          {" "}<Link href="/integrations" className="text-brand underline">API Integrations</Link> sayfasına gelecek.
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Card title="YouTube toplam izlenme" tone="yt"><Num m={d.youtube.total_views} /></Card>
        <Card title="YouTube abone" tone="yt"><Num m={d.youtube.subscribers} /></Card>
        <Card title="YouTube tahmini gelir" tone="yt"><Cash m={d.youtube.estimated_revenue_30d} /></Card>
        <Card title="Etsy sipariş" tone="etsy"><Num m={d.etsy.orders_30d} /></Card>
        <Card title="Etsy satış geliri" tone="etsy"><Cash m={d.etsy.sales_revenue_30d} /></Card>
        <Card title="Etsy net kâr (doğrulanmış)" tone="etsy">
          {np.status === "ok" && np.value?.amount
            ? formatMoney([{ currency: np.value.currency, amount: np.value.amount }])[0]
            : <Muted>{STATUS_TEXT[np.status]}</Muted>}
        </Card>
        <Card title="Toplam gider"><Cash m={d.expenses_30d} /></Card>
        <Card title="Onay bekleyen işlem">
          <Link href="/approvals" className={d.operations.pending_approvals ? "text-etsy" : ""}>
            {d.operations.pending_approvals}
          </Link>
        </Card>
        <Card title="AI ajanlar (çalışan / toplam)">{d.operations.working_agents} / {d.operations.agents}</Card>
        <Card title="Aktif görev">{d.operations.active_tasks}</Card>
        <Card title="Başarısız görev">{d.operations.failed_tasks}</Card>
      </div>

      <section className="rounded-2xl border border-line bg-panel p-4">
        <h2 className="font-semibold">Son tamamlanan görevler</h2>
        {d.recent_completed_tasks.length === 0
          ? <p className="mt-2 text-sm text-muted">Henüz tamamlanan görev yok. CEO Komut Merkezi Phase 2 ile gelecek.</p>
          : <ul className="mt-2 divide-y divide-line text-sm">{d.recent_completed_tasks.map((t) => (
              <li key={t.id} className="flex justify-between py-2"><span>{t.title}</span>
                <span className="text-muted">{t.completed_at && new Date(t.completed_at).toLocaleString("tr-TR")}</span></li>))}
            </ul>}
      </section>
    </div>
  );
}
