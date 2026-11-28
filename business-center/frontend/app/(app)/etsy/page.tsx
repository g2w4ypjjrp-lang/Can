import { DraftListingForm } from "@/components/DraftListingForm";
import { NotConnected, PageHeader, Stat, n } from "@/components/Page";
import { ProposeEdit } from "@/components/ProposeEdit";
import { QuickTask } from "@/components/QuickTask";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type E = { shop: { name: string; currency: string | null } | null; printify_products: number;
  listings: { etsy_listing_id: number; title: string; price_amount: string | null; currency: string | null; quantity: number | null; state: string; tags: string[] }[];
  orders: { etsy_receipt_id: number; status: string; grandtotal_amount: string | null; currency: string | null; ordered_at: string; shipped_at: string | null }[] };

const money = (v: string | null, c: string | null) => (v === null || !c ? "—" : Number(v).toLocaleString("tr-TR", { style: "currency", currency: c }));

export default async function Etsy() {
  const { token, org } = await appContext();
  const d = await api<E>(`/api/organizations/${org.id}/etsy`, token);
  const admin = org.role !== "viewer";
  const weakSeo = d.listings.filter((l) => (l.tags?.length ?? 0) < 13).length;
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader title="Etsy Management" desc={d.shop ? `${d.shop.name} · Printify ürünleri: ${d.printify_products}` : undefined}>
        {admin && <>
          <QuickTask orgId={org.id} agent="etsy_seo" label="SEO denetimi" command="Mağazamdaki listelemelerin SEO'sunu denetle; 13 etiketi eksik olanlara öneri hazırla." />
          <QuickTask orgId={org.id} agent="etsy_sales_analyst" label="Satışları analiz et" command="Etsy mağazamın son 30 günlük performansını analiz et." />
        </>}
      </PageHeader>
      {!d.shop ? <NotConnected what="Etsy mağazası" /> : <>
        {admin && <DraftListingForm orgId={org.id} currency={d.shop.currency} />}
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Aktif listeleme" value={n(d.listings.length)} />
          <Stat label="Son siparişler" value={n(d.orders.length)} />
          <Stat label="13 etiketi eksik listeleme" value={n(weakSeo)} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="overflow-hidden rounded-2xl border border-line bg-panel">
            <h2 className="border-b border-line p-4 font-semibold">Listelemeler</h2>
            <ul className="max-h-[480px] divide-y divide-line overflow-auto">
              {d.listings.map((l) => (
                <li key={l.etsy_listing_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm">
                  <a href={`https://www.etsy.com/listing/${l.etsy_listing_id}`} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate hover:underline">{l.title}</a>
                  <span className={`text-xs ${(l.tags?.length ?? 0) < 13 ? "text-amber-700" : "text-muted"}`}>{l.tags?.length ?? 0}/13 etiket</span>
                  <span className="tabular-nums">{money(l.price_amount, l.currency)}</span>
                  {admin && <div className="w-full"><ProposeEdit orgId={org.id} action="etsy.listing.update" targetId={String(l.etsy_listing_id)}
                    title={l.title} tags={l.tags ?? []} maxTitle={140} maxTags={13} /></div>}
                </li>
              ))}
              {!d.listings.length && <li className="p-4 text-sm text-muted">Listeleme yok. API Integrations'tan senkronlayın.</li>}
            </ul>
          </section>
          <section className="overflow-hidden rounded-2xl border border-line bg-panel">
            <h2 className="border-b border-line p-4 font-semibold">Son siparişler</h2>
            <ul className="max-h-[480px] divide-y divide-line overflow-auto">
              {d.orders.map((o) => (
                <li key={o.etsy_receipt_id} className="flex items-center gap-3 p-3 text-sm">
                  <span className="min-w-0 flex-1">#{o.etsy_receipt_id} <span className="text-xs text-muted">{new Date(o.ordered_at).toLocaleDateString("tr-TR")}</span></span>
                  <span className="rounded-full bg-canvas px-2 py-0.5 text-xs">{o.shipped_at ? "Kargolandı" : o.status}</span>
                  <span className="tabular-nums">{money(o.grandtotal_amount, o.currency)}</span>
                </li>
              ))}
              {!d.orders.length && <li className="p-4 text-sm text-muted">Son 90 günde sipariş yok.</li>}
            </ul>
          </section>
        </div>
      </>}
    </div>
  );
}
