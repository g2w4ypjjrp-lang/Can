import type { Metadata } from 'next';
import Link from 'next/link';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { OpportunityCard, ResearchForm, type Opportunity } from '@/components/market-forms';

export const metadata: Metadata = { title: 'Pazar Araştırma' };

interface ListResp {
  capabilities: { etsyMarketData: boolean; aiAnalysis: boolean };
  items: Array<{
    id: string;
    query: string;
    region: string;
    status: string;
    confidence: string;
    created_at: string;
    opportunities: number;
    error: string | null;
  }>;
}
interface Fact {
  keyword: string;
  activeListings: number;
  priceUsd: { min: number; p25: number; median: number; p75: number; max: number } | null;
  avgFavorers: number | null;
  newListingsShare90d: number | null;
  topTags: Array<{ tag: string; count: number }>;
  sampleSize: number;
}
interface Detail {
  research: {
    id: string;
    query: string;
    region: string;
    status: string;
    confidence: string;
    error: string | null;
    summary: {
      facts?: Fact[];
      analysis?: {
        summary: string;
        seasonality: string;
        keywords: Array<{ keyword: string; trend: string; rationale: string }>;
      } | null;
      web?: { sources: Array<{ url: string; title: string | null }> } | null;
      notes?: string[];
      usage?: {
        inputTokens: number;
        outputTokens: number;
        webSearchRequests: number;
        costUsd: string;
      };
    };
  };
  opportunities: Opportunity[];
  competitors: Array<{
    listing_url: string;
    listing_title: string;
    observed_price: string;
    currency: string;
    signals: { keyword: string; num_favorers: number };
  }>;
}

export default async function MarketResearchPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const list = await api<ListResp>(`/stores/${current.id}/market-research`);
  const id = sp.id && /^[0-9a-f-]{36}$/i.test(sp.id) ? sp.id : list.items[0]?.id;
  const detail = id ? await api<Detail>(`/stores/${current.id}/market-research/${id}`) : null;
  const canEdit = current.role === 'owner' || current.role === 'admin';
  const r = detail?.research;

  return (
    <>
      <PageHeader
        title="Pazar Araştırma"
        description="Etsy pazar verisi (resmî API) + Claude analizi. Satış adetleri Etsy tarafından paylaşılmaz; tahminler işaretlidir."
      />
      <div className="mb-6 space-y-2">
        {!list.capabilities.etsyMarketData && (
          <Notice tone="warn">
            Etsy API anahtarı tanımlı değil: gerçek pazar verisi (ilan sayısı, fiyat dağılımı)
            toplanamaz.
          </Notice>
        )}
        {!list.capabilities.aiAnalysis && (
          <Notice tone="warn">
            ANTHROPIC_API_KEY tanımlı değil: AI analizi ve fırsat önerileri üretilmez.
          </Notice>
        )}
      </div>
      {canEdit && (
        <Card title="Yeni araştırma" className="mb-6">
          <ResearchForm storeId={current.id} />
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-4">
        <Card title="Geçmiş" className="lg:col-span-1">
          {list.items.length === 0 ? (
            <p className="text-sm text-slate-500">Henüz araştırma yok.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {list.items.map((x) => (
                <li key={x.id}>
                  <Link
                    href={`/dashboard/market-research?id=${x.id}`}
                    className={`block rounded-lg px-2 py-1.5 hover:bg-slate-50 ${x.id === id ? 'bg-brand-50 font-medium' : ''}`}
                  >
                    {x.query}{' '}
                    <span className="text-xs text-slate-500">
                      · {x.region} · {x.status} · {x.opportunities} fırsat
                    </span>
                    <span className="block text-xs text-slate-400">{formatDate(x.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-6 lg:col-span-3" data-testid="research-detail">
          {!r ? null : r.status !== 'completed' ? (
            <Card title={`"${r.query}"`}>
              <p className="text-sm text-slate-600">
                Durum: <strong>{r.status}</strong>
                {r.error ? ` — ${r.error}` : ''}. Sayfayı yenileyin.
              </p>
            </Card>
          ) : (
            <>
              <Card title={`"${r.query}" · ${r.region} · güven: ${r.confidence}`}>
                {r.summary.analysis && (
                  <>
                    <p className="text-sm text-slate-800">{r.summary.analysis.summary}</p>
                    <p className="mt-1 text-sm text-slate-600">
                      Sezon: {r.summary.analysis.seasonality}
                    </p>
                  </>
                )}
                {(r.summary.notes ?? []).map((n) => (
                  <p key={n} className="mt-2 text-sm text-amber-800">
                    {n}
                  </p>
                ))}
                {r.summary.usage && (
                  <p className="mt-2 text-xs text-slate-500">
                    AI kullanımı: {r.summary.usage.inputTokens + r.summary.usage.outputTokens}{' '}
                    token, {r.summary.usage.webSearchRequests} web araması, tahmini $
                    {r.summary.usage.costUsd}
                  </p>
                )}
              </Card>
              {(r.summary.facts ?? []).length > 0 && (
                <Card title="Etsy pazar verisi (gerçek, resmî API)">
                  <div className="overflow-x-auto">
                    <table
                      className="w-full min-w-[640px] text-left text-sm"
                      aria-label="Pazar verisi"
                    >
                      <thead className="border-b border-line text-xs uppercase text-slate-500">
                        <tr>
                          <th className="py-2 pr-3">Kelime</th>
                          <th className="py-2 pr-3">Aktif ilan</th>
                          <th className="py-2 pr-3">Fiyat (USD) p25–medyan–p75</th>
                          <th className="py-2 pr-3">Ort. favori</th>
                          <th className="py-2 pr-3">Son 90 gün yeni</th>
                          <th className="py-2">Sık etiketler</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(r.summary.facts ?? []).map((f) => (
                          <tr
                            key={f.keyword}
                            className="border-b border-line align-top last:border-0"
                          >
                            <td className="py-2 pr-3 font-medium">{f.keyword}</td>
                            <td className="py-2 pr-3 tabular-nums">
                              {f.activeListings.toLocaleString('tr-TR')}
                            </td>
                            <td className="py-2 pr-3 tabular-nums">
                              {f.priceUsd
                                ? `${f.priceUsd.p25} – ${f.priceUsd.median} – ${f.priceUsd.p75}`
                                : '—'}
                            </td>
                            <td className="py-2 pr-3 tabular-nums">{f.avgFavorers ?? '—'}</td>
                            <td className="py-2 pr-3 tabular-nums">
                              {f.newListingsShare90d !== null
                                ? `%${Math.round(f.newListingsShare90d * 100)}`
                                : '—'}
                            </td>
                            <td className="py-2 text-xs text-slate-600">
                              {f.topTags
                                .slice(0, 6)
                                .map((t) => t.tag)
                                .join(', ')}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    Örneklem: kelime başına en fazla 200 ilan (Etsy arama sırası). Favori sayısı
                    ilgi göstergesidir, satış değildir.
                  </p>
                </Card>
              )}
              <section aria-label="Fırsatlar" className="space-y-3">
                <h2 className="text-sm font-semibold text-navy-900">
                  Ürün fırsatları ({detail!.opportunities.length})
                </h2>
                {detail!.opportunities.map((o) => (
                  <OpportunityCard key={o.id} storeId={current.id} o={o} canEdit={canEdit} />
                ))}
              </section>
              {r.summary.web && r.summary.web.sources.length > 0 && (
                <Card title="Web kaynakları">
                  <ul className="list-disc space-y-1 pl-5 text-sm">
                    {r.summary.web.sources.map((s) => (
                      <li key={s.url}>
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-brand-600 hover:underline"
                        >
                          {s.title ?? s.url}
                        </a>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
