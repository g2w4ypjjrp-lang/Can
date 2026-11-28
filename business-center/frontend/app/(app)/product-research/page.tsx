import Link from "next/link";
import { Empty, PageHeader } from "@/components/Page";
import { QuickTask } from "@/components/QuickTask";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type R = { products: { id: string; niche: string; idea: string; opportunity_score: number | null }[];
  reports: { id: string; title: string; status: string; completed_at: string | null }[] };

export default async function Research() {
  const { token, org } = await appContext();
  const d = await api<R>(`/api/organizations/${org.id}/research`, token);
  const admin = org.role !== "viewer";
  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader title="Product Research" desc="Ürün, rakip ve trend araştırmaları. Raporlar web kaynaklarıyla birlikte saklanır.">
        {admin && <>
          <QuickTask orgId={org.id} agent="etsy_product_research" label="20 ürün araştır" command="Etsy mağazamda satış potansiyeli olan 20 ürün araştır ve fırsat puanıyla sırala." />
          <QuickTask orgId={org.id} agent="etsy_competitor_analysis" label="Rakip analizi" command="Nişimdeki 8 rakip mağazayı analiz et ve pazar boşluklarını çıkar." />
          <QuickTask orgId={org.id} agent="yt_trend_research" label="YouTube trendleri" command="Kanalımın nişinde son 30 günün trend konularını bul." />
        </>}
      </PageHeader>
      <section>
        <h2 className="mb-3 font-semibold">Araştırma raporları</h2>
        {!d.reports.length ? <Empty>Henüz araştırma yok. Yukarıdaki düğmelerle başlatabilirsiniz.</Empty> : (
          <ul className="divide-y divide-line rounded-2xl border border-line bg-panel">
            {d.reports.map((r) => (
              <li key={r.id}><Link href={`/tasks/${r.id}`} className="flex items-center gap-3 p-4 text-sm hover:bg-canvas">
                <StatusBadge status={r.status} /><span className="min-w-0 flex-1 truncate">{r.title}</span>
                <span className="text-xs text-muted">{r.completed_at ? new Date(r.completed_at).toLocaleDateString("tr-TR") : ""}</span>
              </Link></li>
            ))}
          </ul>
        )}
      </section>
      {d.products.length > 0 && (
        <section>
          <h2 className="mb-3 font-semibold">Kayıtlı ürün fikirleri</h2>
          <ul className="grid gap-3 sm:grid-cols-2">{d.products.map((p) => (
            <li key={p.id} className="rounded-xl border border-line bg-panel p-4 text-sm">
              <div className="flex justify-between gap-2"><span className="font-medium">{p.idea}</span>
                {p.opportunity_score !== null && <span className="tabular-nums text-muted">{p.opportunity_score}/100</span>}</div>
              <p className="text-xs text-muted">{p.niche}</p>
            </li>))}</ul>
        </section>
      )}
    </div>
  );
}
