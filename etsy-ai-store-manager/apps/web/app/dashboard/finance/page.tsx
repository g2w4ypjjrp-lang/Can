import type { Metadata } from 'next';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Kpi, Notice, PageHeader } from '@/components/ui';
import { RecomputeButton, SimulatorForm, VerifyRuleButton } from '@/components/finance-forms';

export const metadata: Metadata = { title: 'Finans ve Kâr' };

interface Summary {
  currency: string;
  period: { from: string; to: string };
  orders: number;
  netRevenue: string;
  variableCostsExAds: string;
  contributionBeforeAds: string;
  adSpendActual: string;
  contributionAfterAds: string;
  estimatedTax: string;
  netAfterTax: string;
  averageContributionPerOrder: string | null;
  costLines: Array<{ code: string; label: string; amount: string }>;
  dataQuality: {
    incompleteOrders: number;
    unverifiedFeeOrders: number;
    ordersWithoutCalculation: number;
  };
  note: string;
}
interface Rule {
  id: string;
  feeType: string;
  rate: string | null;
  fixed: string | null;
  basis: string;
  country: string | null;
  buyerScope: string;
  cap: string | null;
  tier: string | null;
  sourceUrl: string;
  notes: string | null;
  verifiedAt: string | null;
}

const FEE_LABELS: Record<string, string> = {
  listing: 'Listeleme',
  transaction: 'İşlem',
  payment_processing: 'Ödeme işleme',
  currency_conversion: 'Döviz çevirme',
  offsite_ads: 'Offsite Ads',
  regulatory_operating: 'Düzenleyici işletim',
};
const BASIS_LABELS: Record<string, string> = {
  per_listing: 'adet başı',
  item_plus_shipping: 'ürün + kargo',
  order_total: 'sipariş toplamı',
  order_total_incl_tax: 'sipariş toplamı + vergi',
  converted_amount: 'çevrilen tutar',
  item_price: 'ürün fiyatı',
  per_order: 'sipariş başı',
};

export default async function FinancePage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string }>;
}) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const re = /^\d{4}-\d{2}-\d{2}$/;
  const q = new URLSearchParams();
  if (sp.from && re.test(sp.from)) q.set('from', sp.from);
  if (sp.to && re.test(sp.to)) q.set('to', sp.to);
  const [summary, rules, settings] = await Promise.all([
    api<Summary>(`/stores/${current.id}/finance/summary?${q}`),
    api<Rule[]>(`/stores/${current.id}/finance/fee-rules`),
    api<{ sellerCountry: string | null; payoutCurrency: string | null }>(
      `/stores/${current.id}/settings`,
    ),
  ]);
  const c = summary.currency;
  const canAdmin = current.role === 'owner' || current.role === 'admin';
  const relevant = rules.filter((r) => r.country === null || r.country === settings.sellerCountry);
  const unverified = relevant.filter((r) => !r.verifiedAt).length;

  return (
    <>
      <PageHeader
        title="Finans ve Kâr"
        description={`Profit Engine · ${summary.period.from} – ${summary.period.to}`}
      >
        <form className="flex items-end gap-2 text-sm">
          <input
            type="date"
            name="from"
            defaultValue={summary.period.from}
            className="rounded-lg border border-line px-2 py-1.5"
            aria-label="Başlangıç"
          />
          <input
            type="date"
            name="to"
            defaultValue={summary.period.to}
            className="rounded-lg border border-line px-2 py-1.5"
            aria-label="Bitiş"
          />
          <button className="rounded-lg border border-line px-3 py-1.5">Uygula</button>
        </form>
      </PageHeader>

      <div className="mb-6 space-y-2">
        {!settings.sellerCountry && (
          <Notice tone="warn">
            Satıcı (banka) ülkesi ayarlanmadı. Ücretler doğru seçilemez: Ayarlar → Mağaza.
          </Notice>
        )}
        {unverified > 0 && (
          <Notice tone="warn">
            Mağazanız için geçerli {unverified} Etsy ücret kuralı henüz doğrulanmadı. Oranlar Etsy
            Yardım Merkezi’nden alındı (resmî politika sayfası sunucudan erişilemedi); Etsy hesap
            ekstrenizle karşılaştırıp aşağıdan doğrulayın.
          </Notice>
        )}
        {summary.dataQuality.ordersWithoutCalculation + summary.dataQuality.incompleteOrders >
          0 && (
          <Notice>
            {summary.dataQuality.incompleteOrders} siparişte eksik veri (maliyet/ayar),{' '}
            {summary.dataQuality.ordersWithoutCalculation} sipariş henüz hesaplanmadı. Bu
            siparişlerin katkısı tahminidir veya dahil değildir.
          </Notice>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" data-testid="finance-kpis">
        <Kpi
          label="Net satış geliri"
          value={formatMoney(summary.netRevenue, c)}
          hint={`${summary.orders} sipariş`}
        />
        <Kpi label="Katkı (reklam öncesi)" value={formatMoney(summary.contributionBeforeAds, c)} />
        <Kpi
          label="Gerçek reklam harcaması"
          value={formatMoney(summary.adSpendActual, c)}
          hint="Bir kez düşülür"
        />
        <Kpi
          label="Katkı (reklam sonrası)"
          value={formatMoney(summary.contributionAfterAds, c)}
          hint={`Sipariş başı ${formatMoney(summary.averageContributionPerOrder, c)}`}
        />
        <Kpi
          label="Değişken giderler"
          value={formatMoney(summary.variableCostsExAds, c)}
          hint="Reklam hariç"
        />
        <Kpi
          label="Tahmini vergi"
          value={formatMoney(summary.estimatedTax, c)}
          hint="Politikadaki orana göre"
        />
        <Kpi label="Vergi sonrası net" value={formatMoney(summary.netAfterTax, c)} />
        <Kpi
          label="Doğrulanmamış ücretli sipariş"
          value={String(summary.dataQuality.unverifiedFeeOrders)}
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Gider kalemleri (dönem)">
          {summary.costLines.length === 0 ? (
            <p className="text-sm text-slate-500">Hesaplanmış sipariş yok.</p>
          ) : (
            <ul className="divide-y divide-line text-sm">
              {summary.costLines.map((l) => (
                <li key={l.code} className="flex justify-between py-1.5">
                  <span>{l.label}</span>
                  <span className="tabular-nums">{formatMoney(l.amount, c)}</span>
                </li>
              ))}
            </ul>
          )}
          {canAdmin && (
            <div className="mt-4">
              <RecomputeButton storeId={current.id} />
            </div>
          )}
          <p className="mt-3 text-xs text-slate-500">{summary.note}</p>
        </Card>
        <Card title="Kârlılık simülatörü" className="lg:col-span-2">
          <SimulatorForm storeId={current.id} currency={current.currency} />
        </Card>
      </div>

      <Card title="Etsy ücret kuralları" className="mt-6">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm" aria-label="Ücret kuralları">
            <thead className="border-b border-line text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3">Ücret</th>
                <th className="py-2 pr-3">Ülke</th>
                <th className="py-2 pr-3">Oran</th>
                <th className="py-2 pr-3">Sabit</th>
                <th className="py-2 pr-3">Matrah</th>
                <th className="py-2 pr-3">Kaynak</th>
                <th className="py-2">Doğrulama</th>
              </tr>
            </thead>
            <tbody>
              {relevant.map((r) => (
                <tr key={r.id} className="border-b border-line align-top last:border-0">
                  <td className="py-2 pr-3">
                    {FEE_LABELS[r.feeType] ?? r.feeType}
                    {r.tier ? ` (%${r.tier})` : ''}
                    {r.buyerScope !== 'any'
                      ? ` · ${r.buyerScope === 'domestic' ? 'yurt içi' : 'yurt dışı'}`
                      : ''}
                    {r.notes && <span className="block text-xs text-slate-500">{r.notes}</span>}
                  </td>
                  <td className="py-2 pr-3">{r.country ?? 'Tümü'}</td>
                  <td className="py-2 pr-3 tabular-nums">
                    {r.rate ? `%${(Number(r.rate) * 100).toFixed(2).replace(/\.?0+$/, '')}` : '—'}
                  </td>
                  <td className="py-2 pr-3 tabular-nums">
                    {r.fixed ?? '—'}
                    {r.cap ? ` (üst sınır ${r.cap})` : ''}
                  </td>
                  <td className="py-2 pr-3">{BASIS_LABELS[r.basis] ?? r.basis}</td>
                  <td className="py-2 pr-3">
                    <a
                      href={r.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-brand-600 hover:underline"
                    >
                      Etsy ↗
                    </a>
                  </td>
                  <td className="py-2">
                    {r.verifiedAt ? (
                      <span className="text-emerald-700">✓ {formatDate(r.verifiedAt)}</span>
                    ) : canAdmin ? (
                      <VerifyRuleButton storeId={current.id} ruleId={r.id} />
                    ) : (
                      'Bekliyor'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Yalnızca satıcı ülkenize ({settings.sellerCountry ?? 'ayarlanmadı'}) ve tüm ülkelere
          uygulanan kurallar gösterilir.
        </p>
      </Card>
    </>
  );
}
