import type { Metadata } from 'next';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { Notice, PageHeader } from '@/components/ui';
import { OpportunityCard, type Opportunity } from '@/components/market-forms';

export const metadata: Metadata = { title: 'Ürün Fırsatları' };

const FILTERS = [
  ['', 'Tümü'],
  ['new', 'Yeni'],
  ['shortlisted', 'Kısa liste'],
  ['rejected', 'Elenen'],
] as const;

export default async function OpportunitiesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; min?: string }>;
}) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const status = FILTERS.some(([v]) => v === sp.status) ? (sp.status ?? '') : '';
  const min = Math.max(0, Math.min(100, Number(sp.min) || 0));
  const qs = new URLSearchParams({ minScore: String(min) });
  if (status) qs.set('status', status);
  const items = await api<Opportunity[]>(`/stores/${current.id}/opportunities?${qs}`);
  const canEdit = current.role === 'owner' || current.role === 'admin';
  return (
    <>
      <PageHeader
        title="Ürün Fırsatları"
        description="Puan = 35×kâr + 35×düşük rekabet + 30×ilgi − fikri mülkiyet cezası. Kâr, Profit Engine ile hesaplanır."
      />
      <form className="mb-4 flex flex-wrap items-end gap-2 text-sm">
        <select
          name="status"
          defaultValue={status}
          className="rounded-lg border border-line px-3 py-2"
          aria-label="Durum"
        >
          {FILTERS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2">
          Min. puan{' '}
          <input
            name="min"
            type="number"
            min={0}
            max={100}
            defaultValue={min}
            className="w-20 rounded-lg border border-line px-2 py-2"
          />
        </label>
        <button className="rounded-lg border border-line px-3 py-2">Filtrele</button>
      </form>
      {items.length === 0 ? (
        <Notice>Fırsat yok. Pazar Araştırma sayfasından bir araştırma başlatın.</Notice>
      ) : (
        <div className="space-y-3">
          {items.map((o) => (
            <OpportunityCard key={o.id} storeId={current.id} o={o} canEdit={canEdit} />
          ))}
        </div>
      )}
      <p className="mt-6 text-xs text-slate-500">
        Kâr hedefini karşılamayan (zarar) veya yüksek fikri mülkiyet riski taşıyan fikirler otomatik
        elenir. Tüm talep göstergeleri tahmindir; Etsy rakip satış verisi sağlamaz.
      </p>
    </>
  );
}
