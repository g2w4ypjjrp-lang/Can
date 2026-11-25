import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import type { ListingDto } from '@esm/shared';
import { api, ApiError } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { ListingChangeForm } from '@/components/etsy-forms';

export const metadata: Metadata = { title: 'İlan' };

export default async function ListingPage({ params }: { params: Promise<{ listingId: string }> }) {
  const { listingId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(listingId)) notFound();
  const { current } = await loadStores();
  if (!current) notFound();
  let listing: ListingDto;
  try {
    listing = await api<ListingDto>(`/stores/${current.id}/listings/${listingId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const canEdit = current.role === 'owner' || current.role === 'admin';
  return (
    <>
      <PageHeader
        title={listing.title}
        description={`Etsy #${listing.etsyListingId ?? '—'} · ${listing.state}`}
      >
        <Link href="/dashboard/etsy" className="text-sm text-brand-600 hover:underline">
          ← İlanlar
        </Link>
      </PageHeader>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Mevcut bilgiler">
          {listing.primaryImageUrl && (
            <img
              src={listing.primaryImageUrl}
              alt=""
              className="mb-4 w-full rounded-lg object-cover"
            />
          )}
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Fiyat</dt>
              <dd>{listing.currency ? formatMoney(listing.price, listing.currency) : '—'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Stok</dt>
              <dd>{listing.quantity ?? '—'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Favori</dt>
              <dd>{listing.numFavorers ?? '—'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Etsy’de güncellenme</dt>
              <dd>{formatDate(listing.etsyUpdatedAt)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Son senkronizasyon</dt>
              <dd>{formatDate(listing.lastSyncedAt)}</dd>
            </div>
          </dl>
          {listing.etsyUrl && (
            <a
              href={listing.etsyUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-block text-sm text-brand-600 hover:underline"
            >
              Etsy’de görüntüle ↗
            </a>
          )}
          <p className="mt-4 text-xs text-slate-500">
            Fiyat ve stok değişiklikleri Profit Engine (FAZ 4) ile kârlılık kontrolünden geçtikten
            sonra açılacak.
          </p>
        </Card>
        <Card title="Değişiklik öner" className="lg:col-span-2">
          {canEdit ? (
            <ListingChangeForm storeId={current.id} listing={listing} />
          ) : (
            <Notice>Bu ilanda değişiklik önermek için yönetici yetkisi gerekir.</Notice>
          )}
        </Card>
      </div>
    </>
  );
}
