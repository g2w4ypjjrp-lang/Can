import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import type { ListingDto, StoreSettingsDto } from '@esm/shared';
import { api, ApiError } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate, formatMoney } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { ListingChangeForm } from '@/components/etsy-forms';
import {
  RequestSeoForm,
  SeoDraftCard,
  TranslateForm,
  TranslationCard,
  type SeoDraft,
  type Translation,
} from '@/components/seo-forms';

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
  const [settings, drafts, translations] = await Promise.all([
    api<StoreSettingsDto>(`/stores/${current.id}/settings`),
    api<SeoDraft[]>(`/stores/${current.id}/seo-drafts?listingId=${listingId}`),
    api<Translation[]>(`/stores/${current.id}/listings/${listingId}/translations`),
  ]);
  const path = `/dashboard/etsy/listings/${listingId}`;
  const otherLanguages = settings.languages.filter((l) => l !== settings.defaultLanguage);
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
      <Card title="SEO önerileri" className="mt-6">
        {canEdit && (
          <div className="mb-4">
            <RequestSeoForm
              storeId={current.id}
              target={{ listingId }}
              languages={[settings.defaultLanguage]}
              path={path}
            />
            <p className="mt-1 text-xs text-slate-500">
              Claude, mağazanızın gerçek Etsy anahtar kelime verisini (Pazar Araştırma) kullanır;
              sonuç Etsy kuralları ve spam kontrolünden geçer. Uygulama yalnızca onaydan sonra
              yapılır.
            </p>
          </div>
        )}
        {drafts.length === 0 ? (
          <p className="text-sm text-slate-500">Henüz öneri yok.</p>
        ) : (
          <div className="space-y-4">
            {drafts.slice(0, 5).map((d) => (
              <SeoDraftCard key={d.id} storeId={current.id} d={d} canEdit={canEdit} path={path} />
            ))}
          </div>
        )}
      </Card>
      <Card title={`Diller (ana dil: ${settings.defaultLanguage})`} className="mt-6">
        {canEdit && (
          <div className="mb-4">
            <TranslateForm
              storeId={current.id}
              listingId={listingId}
              languages={otherLanguages}
              path={path}
            />
            <p className="mt-1 text-xs text-slate-500">
              Etiketler hedef dilde yeniden araştırılır. Sayılar ve ürün üzerindeki metin korunur;
              her çeviri geri çeviri ile insan incelemesinden sonra onaya gider.
            </p>
          </div>
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          {translations.map((t) => (
            <TranslationCard key={t.id} storeId={current.id} t={t} canEdit={canEdit} path={path} />
          ))}
        </div>
      </Card>
    </>
  );
}
