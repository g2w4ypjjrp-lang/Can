import type { Metadata } from 'next';
import Link from 'next/link';
import type { ApprovalDto } from '@esm/shared';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate } from '@/lib/format';
import { Card, Kpi, Notice, PageHeader } from '@/components/ui';
import {
  AccountForm,
  ConfirmManualForm,
  CsvImportForm,
  LedgerMappingForm,
  MetaConnectForm,
  PolicyForm,
  ProposalForm,
  SubmitProposalForm,
  SyncButton,
} from '@/components/ads-forms';

export const metadata: Metadata = { title: 'Reklam Yönetimi' };

interface Overview {
  policy: {
    configured: boolean;
    dailyCap: string;
    monthlyCap: string | null;
    currency: string;
    minClicksForDecision: number;
  };
  economics: {
    aov: string | null;
    contributionBeforeAds: string | null;
    targetContribution: string;
    breakEvenRoas: string | null;
    targetRoas: string | null;
    maxCpa: string | null;
    sampleOrders: number;
  };
  spend: { today: string; month: string; period: string };
  activeDailyBudgets: string;
  overCap: boolean;
  monthOverCap: boolean;
  campaigns: Array<{
    campaignId: string;
    name: string;
    platform: string;
    status: string;
    dailyBudget: string | null;
    clicks: number;
    spend: string;
    conversions: string;
    conversionValue: string;
    kpis: { roas: string | null; cpc: string | null; cpa: string | null; ctr: string | null };
    verdict: string;
    reason: string;
  }>;
  note: string;
}
interface Accounts {
  capabilities: Record<string, { reporting: string; management: string; note: string }>;
  accounts: Array<{
    id: string;
    platform: string;
    name: string;
    externalAccountId: string;
    currency: string;
    spendSource: string;
    reporting: string;
    lastSyncedAt: string | null;
    lastError: string | null;
    campaigns: number;
  }>;
}
interface Proposal {
  id: string;
  totalDailyBudget: string;
  currency: string;
  status: string;
  createdAt: string;
  allocations: Array<{
    campaignId: string;
    name: string;
    platform: string;
    currentDailyBudget: string | null;
    proposedDailyBudget: string;
    verdict: string;
    reason: string;
  }>;
}

const PLATFORM: Record<string, string> = {
  etsy_ads: 'Etsy Ads',
  meta_ads: 'Meta',
  google_ads: 'Google',
  pinterest_ads: 'Pinterest',
  tiktok_ads: 'TikTok',
};
const VERDICT: Record<string, [string, string]> = {
  insufficient_data: ['Veri yetersiz', 'bg-slate-100 text-slate-700'],
  unprofitable: ['Zarar', 'bg-red-100 text-red-800'],
  below_target: ['Hedef altı', 'bg-amber-100 text-amber-900'],
  on_target: ['Hedefte', 'bg-emerald-100 text-emerald-800'],
  scale: ['Ölçeklenebilir', 'bg-emerald-200 text-emerald-900'],
};

export default async function AdsPage() {
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const canEdit = current.role === 'owner' || current.role === 'admin';
  const [o, acc, proposals, approvals] = await Promise.all([
    api<Overview>(`/stores/${current.id}/ads/overview?days=30`),
    api<Accounts>(`/stores/${current.id}/ads/accounts`),
    api<Proposal[]>(`/stores/${current.id}/ads/proposals`),
    api<ApprovalDto[]>(`/stores/${current.id}/approvals`),
  ]);
  const ledger = canEdit
    ? await api<{
        mapped: string[];
        types: Array<{
          ledgerType: string;
          entries: number;
          total: string;
          currency: string;
          example: string | null;
          suggested: boolean;
        }>;
      }>(`/stores/${current.id}/ads/etsy-ledger/types`)
    : null;
  const adApprovals = approvals.filter((a) =>
    ['allocate_ad_budget', 'increase_ad_budget', 'start_ad_campaign'].includes(a.actionType),
  );
  const awaiting = adApprovals.filter((a) => a.status === 'awaiting_manual');
  const pending = adApprovals.filter((a) => a.status === 'pending');
  const latest = proposals[0];
  const cur = o.policy.currency;
  return (
    <>
      <PageHeader
        title="Reklam Yönetimi"
        description="Kâr odaklı reklam: başa baş ROAS, kullanıcı bütçe sınırı ve onaylı bütçe dağıtımı"
      >
        {canEdit && <SyncButton storeId={current.id} />}
      </PageHeader>
      {!o.policy.configured && (
        <Notice tone="warn">
          Önce günlük reklam bütçesi üst sınırını belirleyin. Sınır olmadan bütçe önerisi
          oluşturulmaz.
        </Notice>
      )}
      {o.overCap && (
        <Notice tone="warn">
          Aktif kampanyaların günlük bütçe toplamı ({o.activeDailyBudgets} {cur}) sınırı aşıyor.
        </Notice>
      )}
      {o.monthOverCap && <Notice tone="warn">Bu ayki harcama aylık sınırı aştı.</Notice>}

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Bugün / günlük sınır"
          value={`${o.spend.today} / ${o.policy.dailyCap} ${cur}`}
        />
        <Kpi
          label="Bu ay harcama"
          value={`${o.spend.month} ${cur}`}
          hint={o.policy.monthlyCap ? `sınır ${o.policy.monthlyCap}` : 'aylık sınır yok'}
        />
        <Kpi
          label="Başa baş ROAS"
          value={o.economics.breakEvenRoas ?? '—'}
          hint={`AOV ${o.economics.aov ?? '—'} · reklamsız katkı ${o.economics.contributionBeforeAds ?? '—'}`}
        />
        <Kpi
          label="Hedef ROAS"
          value={o.economics.targetRoas ?? '—'}
          hint={`sipariş başı ${o.economics.targetContribution} katkı korunur · azami CPA ${o.economics.maxCpa ?? '—'}`}
        />
      </div>
      {o.economics.sampleOrders === 0 && (
        <p className="mt-2 text-xs text-amber-800">
          Kârlılığı hesaplanmış sipariş yok: başa baş ROAS bilinmiyor, kampanyalar “veri yetersiz”
          sayılır.
        </p>
      )}

      <Card title="Kampanyalar (son 30 gün)" className="mt-6">
        {o.campaigns.length === 0 ? (
          <p className="text-sm text-slate-500">
            Henüz kampanya verisi yok. Meta’yı bağlayın veya rapor içe aktarın.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm" aria-label="Kampanyalar">
              <thead className="border-b border-line text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Kampanya</th>
                  <th className="py-2 pr-3">Harcama</th>
                  <th className="py-2 pr-3">Tıklama</th>
                  <th className="py-2 pr-3">Sipariş</th>
                  <th className="py-2 pr-3">Gelir</th>
                  <th className="py-2 pr-3">ROAS</th>
                  <th className="py-2 pr-3">Günlük bütçe</th>
                  <th className="py-2">Karar</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {o.campaigns.map((c) => {
                  const [vl, vc] = VERDICT[c.verdict] ?? [c.verdict, ''];
                  return (
                    <tr key={c.campaignId} className="align-top">
                      <td className="py-2 pr-3">
                        <span className="font-medium">{c.name}</span>
                        <span className="block text-xs text-slate-500">
                          {PLATFORM[c.platform]} · {c.status}
                        </span>
                      </td>
                      <td className="py-2 pr-3 tabular-nums">{Number(c.spend).toFixed(2)}</td>
                      <td className="py-2 pr-3 tabular-nums">{c.clicks}</td>
                      <td className="py-2 pr-3 tabular-nums">{Number(c.conversions)}</td>
                      <td className="py-2 pr-3 tabular-nums">
                        {Number(c.conversionValue).toFixed(2)}
                      </td>
                      <td className="py-2 pr-3 tabular-nums font-semibold">{c.kpis.roas ?? '—'}</td>
                      <td className="py-2 pr-3 tabular-nums">{c.dailyBudget ?? '—'}</td>
                      <td className="py-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${vc}`}>
                          {vl}
                        </span>
                        <span className="mt-1 block max-w-xs text-xs text-slate-600">
                          {c.reason}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Platform raporlarındaki sipariş/gelir platformun kendi atfıdır ve fazla sayabilir.{' '}
          {o.note}
        </p>
      </Card>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title="Bütçe sınırı (sizin belirlediğiniz)">
          {canEdit ? (
            <PolicyForm storeId={current.id} policy={o.policy} />
          ) : (
            <p className="text-sm">
              Günlük {o.policy.dailyCap} {cur}
            </p>
          )}
        </Card>
        <Card title="Bütçe dağıtımı">
          {canEdit && o.policy.configured && (
            <ProposalForm storeId={current.id} cap={o.policy.dailyCap} />
          )}
          {latest ? (
            <div className="mt-3" aria-label="Son öneri">
              <p className="text-sm">
                Günlük toplam{' '}
                <strong>
                  {latest.totalDailyBudget} {latest.currency}
                </strong>{' '}
                · durum <span data-testid="proposal-status">{latest.status}</span> ·{' '}
                {formatDate(latest.createdAt)}
              </p>
              <ul className="mt-2 space-y-1 text-sm">
                {latest.allocations.map((a) => (
                  <li key={a.campaignId}>
                    {PLATFORM[a.platform]} · {a.name}: {a.currentDailyBudget ?? '—'} →{' '}
                    <strong>{a.proposedDailyBudget}</strong>
                    {a.proposedDailyBudget === '0.00' ? ' (durdur)' : ''}
                  </li>
                ))}
              </ul>
              {canEdit && latest.status === 'draft' && (
                <SubmitProposalForm storeId={current.id} proposalId={latest.id} />
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-500">Henüz öneri yok.</p>
          )}
          <p className="mt-3 text-xs text-slate-500">
            Dağıtım: zarar eden kampanyalar 0 (durdur), verisi yetersizlere küçük test bütçesi,
            kalan ROAS’a göre. Toplam hiçbir zaman sınırı aşmaz.
          </p>
        </Card>
      </div>

      {(pending.length > 0 || awaiting.length > 0) && (
        <Card title="Reklam onayları" className="mt-6">
          {pending.length > 0 && (
            <p className="text-sm">
              {pending.length} istek onay bekliyor:{' '}
              <Link href="/dashboard/etsy#approvals" className="text-brand-600 hover:underline">
                Onaylar
              </Link>
            </p>
          )}
          {awaiting.map((a) => (
            <article
              key={a.id}
              className="mt-3 rounded-xl border border-line p-3"
              aria-label={`Manuel uygulama: ${a.title}`}
            >
              <p className="text-sm font-medium">{a.title}</p>
              <pre className="mt-1 whitespace-pre-wrap text-xs text-slate-600">{a.what}</pre>
              <p className="mt-1 text-xs text-amber-800">
                Onaylandı. Bu değişikliği ilgili reklam panelinde uygulayın (resmî API ile otomatik
                yapılamıyor), sonra işaretleyin.
              </p>
              {canEdit && <ConfirmManualForm storeId={current.id} approvalId={a.id} />}
            </article>
          ))}
        </Card>
      )}

      <Card title="Reklam hesapları" className="mt-6">
        <ul className="divide-y divide-line text-sm">
          {acc.accounts.map((a) => (
            <li key={a.id} className="py-2">
              <span className="font-medium">
                {PLATFORM[a.platform]} · {a.name}
              </span>{' '}
              ({a.externalAccountId}) · rapor: {a.reporting === 'api' ? 'API' : 'CSV/elle'} ·
              harcama kaynağı:{' '}
              {a.spendSource === 'ledger' ? 'Etsy ödeme defteri' : 'kampanya raporu'} ·{' '}
              {a.campaigns} kampanya
              {a.lastSyncedAt && ` · son senk. ${formatDate(a.lastSyncedAt)}`}
              {a.lastError && <span className="block text-xs text-red-700">{a.lastError}</span>}
            </li>
          ))}
          {acc.accounts.length === 0 && <li className="py-2 text-slate-500">Henüz hesap yok.</li>}
        </ul>
        {canEdit && (
          <div className="mt-4 grid gap-6 lg:grid-cols-2">
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                Meta (Facebook/Instagram) — API raporlama
              </h3>
              <MetaConnectForm storeId={current.id} />
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                Diğer platformlar — hesap ekle (CSV/elle)
              </h3>
              <AccountForm storeId={current.id} />
            </div>
            <div>
              <h3 className="mb-2 text-sm font-semibold">Günlük rapor içe aktar (CSV)</h3>
              <CsvImportForm
                storeId={current.id}
                accounts={acc.accounts
                  .filter((a) => a.reporting !== 'api' && a.spendSource !== 'ledger')
                  .map((a) => ({ id: a.id, label: `${PLATFORM[a.platform]} · ${a.name}` }))}
              />
            </div>
            {ledger && (
              <div>
                <h3 className="mb-2 text-sm font-semibold">
                  Etsy Ads gerçek harcaması (Etsy ödeme defteri)
                </h3>
                <LedgerMappingForm
                  storeId={current.id}
                  types={ledger.types}
                  mapped={ledger.mapped}
                />
              </div>
            )}
          </div>
        )}
      </Card>

      <Card title="Platform yetenekleri (resmî API durumu)" className="mt-6">
        <ul className="space-y-2 text-sm">
          {Object.entries(acc.capabilities).map(([k, c]) => (
            <li key={k}>
              <span className="font-medium">{PLATFORM[k]}</span> · rapor: {c.reporting} · yönetim:{' '}
              {c.management === 'manual' ? 'onaylı manuel' : 'API'}
              <span className="block text-xs text-slate-500">{c.note}</span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
