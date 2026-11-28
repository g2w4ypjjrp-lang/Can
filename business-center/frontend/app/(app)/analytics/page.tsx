import Link from "next/link";
import { BarChart } from "@/components/BarChart";
import { NotConnected, PageHeader } from "@/components/Page";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type A = { days: number; youtube: { day: string; views: number; minutes: string; net_subs: number; has_data: boolean }[] | null;
  etsy: { day: string; orders: number }[] | null };

const label = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("tr-TR", { day: "2-digit", month: "short" });

export default async function Analytics({ searchParams }: { searchParams: Promise<{ days?: string }> }) {
  const { token, org } = await appContext();
  const sp = await searchParams;
  const days = ["7", "30", "90"].includes(sp.days ?? "") ? Number(sp.days) : 30;
  const d = await api<A>(`/api/organizations/${org.id}/analytics?days=${days}`, token);
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader title="Analytics" desc="Günlük veriler. Veri olmayan günler grafikte boş, tabloda “—” görünür.">
        <div className="flex rounded-xl border border-line bg-panel p-1 text-sm">
          {[7, 30, 90].map((x) => (
            <Link key={x} href={`/analytics?days=${x}`} aria-current={x === days ? "page" : undefined}
              className={`rounded-lg px-3 py-1 ${x === days ? "bg-brand text-white" : "text-muted hover:bg-canvas"}`}>{x} gün</Link>
          ))}
        </div>
      </PageHeader>
      {d.youtube ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <BarChart title="YouTube izlenme" unit="izlenme" color="#e11d48"
            points={d.youtube.map((r) => ({ label: label(r.day), value: r.views, empty: !r.has_data }))} />
          <BarChart title="İzlenme süresi" unit="dakika" color="#be123c"
            points={d.youtube.map((r) => ({ label: label(r.day), value: Number(r.minutes), empty: !r.has_data }))} />
        </div>
      ) : <NotConnected what="YouTube" />}
      <div className="grid gap-4 lg:grid-cols-2">
        {d.etsy ? (
          <BarChart title="Etsy siparişleri" unit="sipariş" color="#ea580c" integer
            points={d.etsy.map((r) => ({ label: label(r.day), value: r.orders }))} />
        ) : <NotConnected what="Etsy" />}
        {d.youtube && (
          <BarChart title="Net abone artışı (düşüş olan günler 0)" unit="abone" color="#9f1239" integer
            points={d.youtube.map((r) => ({ label: label(r.day), value: Math.max(0, r.net_subs), empty: !r.has_data }))} />
        )}
      </div>
    </div>
  );
}
