import type { Metadata } from 'next';
import Link from 'next/link';
import type { ApprovalDto, EtsyConnectionDto, ListingDto } from '@esm/shared';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Kpi, Notice, PageHeader } from '@/components/ui';
import {
  ApprovalCard,
  ConnectEtsyButton,
  DisconnectEtsyForm,
  SyncEtsyButton,
} from '@/components/etsy-forms';

export const metadata: Metadata = { title: 'Etsy Mağazam' };

const STATES = [
  ['', 'Tümü'],
  ['active', 'Aktif'],
  ['draft', 'Taslak'],
  ['inactive', 'Pasif'],
  ['sold_out', 'Tükendi'],
  ['expired', 'Süresi dolmuş'],
] as const;

type Search = Promise<{
  state?: string;
  q?: string;
  page?: string;
  connected?: string;
  error?: string;
}>;

export default async function EtsyPage({ searchParams }: { searchParams: Search }) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) {
    return (
      <>
        <PageHeader title="Etsy Mağazam" />
        <Notice>Önce Genel Bakış sayfasından mağaza kaydı oluşturun.</Notice>
      </>
    );
  }
  const state = STATES.some(([v]) => v === sp.state) ? (sp.state ?? '') : '';
  const page = Math.max(1, Number(sp.page) || 1);
  const limit = 25;
  const qs = new URLSearchParams({ limit: String(limit), offset: String((page - 1) * limit) });
  if (state) qs.set('state', state);
  if (sp.q) qs.set('q', sp.q.slice(0, 100));

  const [conn, listings, approvals] = await Promise.all([
    api<EtsyConnectionDto>(`/stores/${current.id}/integrations/etsy`),
    api<{ total: number; items: ListingDto[] }>(`/stores/${current.id}/listings?${qs}`),
    api<ApprovalDto[]>(`/stores/${current.id}/approvals`),
  ]);
  const pending = approvals.filter((a) => a.status === 'pending');
  const recent = approvals.filter((a) => a.status !== 'pending').slice(0, 5);
  const isOwner = current.role === 'owner';
  const connected = conn.status === 'active';

  return (
    <>
      <PageHeader
        title="Etsy Mağazam"
        description="Resmî Etsy Open API v3 bağlantısı, ilanlar ve onaylı değişiklikler"
      >
        {conn.shopUrl && (
          <a
            href={conn.shopUrl}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-brand-600 hover:underline"
          >
            Etsy’de aç ↗
          </a>
        )}
      </PageHeader>

      <div className="mb-6 space-y-2">
        {sp.connected && (
          <Notice>Etsy mağazanız bağlandı. İlk içe aktarma arka planda çalışıyor.</Notice>
        )}
        {sp.error && <Notice tone="warn">Bağlantı başarısız: {sp.error.slice(0, 200)}</Notice>}
        {!conn.configured && (
          <Notice tone="warn">
            Etsy entegrasyonu sunucuda yapılandırılmadı. Sunucu <code>.env</code> dosyasına ekleyin:{' '}
            <strong>{conn.missingConfig.join(', ')}</strong>. (Etsy geliştirici portalında uygulama
            oluşturup keystring ve shared secret alın; callback URL’sini{' '}
            <code>ETSY_REDIRECT_URI</code> ile birebir aynı kaydedin.)
          </Notice>
        )}
        {conn.status === 'expired' && (
          <Notice tone="warn">Etsy oturumu yenilenemedi. Mağazayı yeniden bağlayın.</Notice>
        )}
        {conn.lastError && connected && (
          <Notice tone="warn">Son senkronizasyon hatası: {conn.lastError}</Notice>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Bağlantı" className="lg:col-span-2">
          <dl className="grid gap-3 text-sm sm:grid-cols-2" data-testid="etsy-connection">
            <Row k="Durum" v={STATUS_LABELS[conn.status] ?? conn.status} />
            <Row k="Etsy mağazası" v={conn.shopName ?? '—'} />
            <Row k="Son senkronizasyon" v={formatDate(conn.lastSyncedAt)} />
            <Row k="Erişim izinleri" v={conn.scopes.join(', ') || '—'} />
          </dl>
          <div className="mt-5 flex flex-wrap items-start gap-3">
            {conn.configured &&
              isOwner &&
              (!connected ? (
                <ConnectEtsyButton
                  storeId={current.id}
                  label={conn.status === 'not_connected' ? 'Etsy ile bağlan' : 'Yeniden bağlan'}
                />
              ) : null)}
            {connected && current.role !== 'viewer' && current.role !== 'analyst' && (
              <SyncEtsyButton storeId={current.id} />
            )}
          </div>
          {!isOwner && !connected && (
            <p className="mt-3 text-sm text-slate-500">
              Bağlantıyı yalnızca mağaza sahibi kurabilir.
            </p>
          )}
        </Card>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-1">
          <Kpi label="İçe aktarılan ilan" value={String(conn.counts.listings)} />
          <Kpi label="İçe aktarılan sipariş" value={String(conn.counts.orders)} />
        </div>
      </div>

      {pending.length > 0 && (
        <section className="mt-6" id="approvals" aria-label="Onay bekleyen değişiklikler">
          <h2 className="mb-3 text-sm font-semibold text-navy-900">
            Onay bekleyen değişiklikler ({pending.length})
          </h2>
          <div className="space-y-3">
            {pending.map((a) => (
              <ApprovalCard key={a.id} storeId={current.id} a={a} />
            ))}
          </div>
        </section>
      )}

      <Card title={`İlanlar (${listings.total})`} className="mt-6">
        <form className="mb-4 flex flex-wrap gap-2" role="search">
          <select
            name="state"
            defaultValue={state}
            className="rounded-lg border border-line px-3 py-2 text-sm"
            aria-label="Durum"
          >
            {STATES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <input
            name="q"
            defaultValue={sp.q ?? ''}
            placeholder="Başlıkta ara"
            className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2 text-sm"
          />
          <button className="rounded-lg border border-line px-3 py-2 text-sm">Filtrele</button>
        </form>
        {listings.items.length === 0 ? (
          <p className="text-sm text-slate-500">
            {connected
              ? 'Bu filtrede ilan yok.'
              : 'Etsy bağlandığında ilanlarınız burada görünecek.'}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-line text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-2 pr-3">İlan</th>
                  <th className="py-2 pr-3">Durum</th>
                  <th className="py-2 pr-3">Fiyat</th>
                  <th className="py-2 pr-3">Stok</th>
                  <th className="py-2 pr-3">Favori</th>
                  <th className="py-2">Etiket</th>
                </tr>
              </thead>
              <tbody>
                {listings.items.map((l) => (
                  <tr key={l.id} className="border-b border-line last:border-0">
                    <td className="py-2 pr-3">
                      <Link
                        href={`/dashboard/etsy/listings/${l.id}`}
                        className="flex items-center gap-3 hover:underline"
                      >
                        {l.primaryImageUrl ? (
                          <img
                            src={l.primaryImageUrl}
                            alt=""
                            className="h-10 w-10 rounded object-cover"
                            loading="lazy"
                          />
                        ) : (
                          <span className="h-10 w-10 rounded bg-slate-100" />
                        )}
                        <span className="line-clamp-2 text-navy-900">{l.title}</span>
                      </Link>
                    </td>
                    <td className="py-2 pr-3 text-slate-600">{l.state}</td>
                    <td className="py-2 pr-3 tabular-nums">
                      {l.currency ? formatMoney(l.price, l.currency) : '—'}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">{l.quantity ?? '—'}</td>
                    <td className="py-2 pr-3 tabular-nums">{l.numFavorers ?? '—'}</td>
                    <td className="py-2 tabular-nums">{l.tags.length}/13</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {listings.total > limit && (
          <nav className="mt-4 flex items-center justify-between text-sm" aria-label="Sayfalama">
            <PageLink sp={sp} page={page - 1} disabled={page <= 1} label="← Önceki" />
            <span className="text-slate-500">
              Sayfa {page} / {Math.ceil(listings.total / limit)}
            </span>
            <PageLink
              sp={sp}
              page={page + 1}
              disabled={page * limit >= listings.total}
              label="Sonraki →"
            />
          </nav>
        )}
      </Card>

      {recent.length > 0 && (
        <Card title="Son kararlar" className="mt-6">
          <ul className="divide-y divide-line text-sm">
            {recent.map((a) => (
              <li
                key={a.id}
                className="flex flex-wrap justify-between gap-2 py-2"
                data-testid="decision"
              >
                <span className="text-slate-700">{a.title}</span>
                <span className="text-slate-500">
                  {DECISION_LABELS[a.status] ?? a.status}
                  {a.executionResult && 'error' in a.executionResult
                    ? ` — ${String(a.executionResult.error)}`
                    : ''}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Etsy API’nin izin vermediği işlemler" className="mt-6">
        <p className="mb-3 text-sm text-slate-600">
          Resmî Open API v3 şemasında bulunmayan işlemler otomatikleştirilmez; bunlar için öneri +
          manuel uygulama akışı kullanılır.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
          {Object.values(conn.unsupportedOperations).map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </Card>

      {isOwner && (connected || conn.status === 'expired') && (
        <Card title="Bağlantıyı kes" className="mt-6">
          <DisconnectEtsyForm storeId={current.id} />
        </Card>
      )}
    </>
  );
}

const DECISION_LABELS: Record<string, string> = {
  approved: 'Onaylandı, uygulanıyor',
  executing: 'Uygulanıyor',
  executed: 'Etsy’ye uygulandı',
  failed: 'Uygulanamadı',
  rejected: 'Reddedildi',
  expired: 'Süresi doldu',
  cancelled: 'İptal edildi',
};

const STATUS_LABELS: Record<string, string> = {
  not_connected: 'Bağlı değil',
  pending: 'Bekliyor',
  active: 'Bağlı',
  expired: 'Yeniden bağlanmalı',
  revoked: 'Bağlantı kesildi',
  error: 'Hata',
};

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{k}</dt>
      <dd className="text-slate-800">{v}</dd>
    </div>
  );
}

function PageLink({
  sp,
  page,
  disabled,
  label,
}: {
  sp: Record<string, string | undefined>;
  page: number;
  disabled: boolean;
  label: string;
}) {
  if (disabled) return <span className="text-slate-300">{label}</span>;
  const q = new URLSearchParams();
  if (sp.state) q.set('state', sp.state);
  if (sp.q) q.set('q', sp.q);
  q.set('page', String(page));
  return (
    <Link href={`/dashboard/etsy?${q}`} className="text-brand-600 hover:underline">
      {label}
    </Link>
  );
}
