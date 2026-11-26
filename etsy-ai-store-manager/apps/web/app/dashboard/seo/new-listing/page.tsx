import type { Metadata } from 'next';
import Link from 'next/link';
import { api, ApiError } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { DraftListingForm, type ListingOptions } from '@/components/seo-forms';

export const metadata: Metadata = { title: 'Yeni Etsy ilanı' };

export default async function NewListingPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const sp = await searchParams;
  const q = (sp.q ?? '').slice(0, 60);
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  if (current.role !== 'owner' && current.role !== 'admin')
    return <Notice>Bu sayfa yönetici yetkisi gerektirir.</Notice>;
  const options = await api<ListingOptions>(`/stores/${current.id}/etsy/listing-options`);
  let taxonomy: Array<{ id: number; path: string; leaf: boolean }> = [];
  let taxonomyError: string | null = null;
  if (q) {
    try {
      taxonomy = await api(`/stores/${current.id}/etsy/taxonomy?q=${encodeURIComponent(q)}`);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      taxonomyError = e.message;
    }
  }
  return (
    <>
      <PageHeader
        title="Yeni Etsy taslak ilanı"
        description="createDraftListing — onaydan sonra Etsy’de görünmeyen TASLAK ilan açılır"
      >
        <Link href="/dashboard/seo" className="text-sm text-brand-600 hover:underline">
          ← SEO Merkezi
        </Link>
      </PageHeader>
      <Notice>
        Printify ürünleri için bu formu kullanmayın: Printify, yayın onayıyla Etsy ilanını kendisi
        oluşturur (çift ilan önlenir). Bu form kendi ürettiğiniz veya Printify dışı ürünler içindir.
        Görseller Etsy’de eklenir; yayınlama ayrıca yapılır.
      </Notice>
      {!options.connected ? (
        <Notice tone="warn">Etsy bağlı değil. Etsy Mağazam sayfasından bağlayın.</Notice>
      ) : (
        <>
          <Card title="1. Kategori ara" className="mt-6">
            <form className="flex gap-2" aria-label="Kategori ara">
              <input
                name="q"
                defaultValue={q}
                placeholder="ör. t-shirt, mug, poster"
                className="w-full rounded-lg border border-line px-3 py-2 text-sm"
              />
              <button className="rounded-lg border border-line px-3 py-2 text-sm">Ara</button>
            </form>
            {taxonomyError && <p className="mt-2 text-sm text-red-700">{taxonomyError}</p>}
            {q && !taxonomyError && (
              <p className="mt-2 text-xs text-slate-500">
                {taxonomy.filter((t) => t.leaf).length} uygun kategori
              </p>
            )}
          </Card>
          {q && taxonomy.some((t) => t.leaf) && (
            <Card title="2. İlan bilgileri" className="mt-6">
              <p className="mb-3 text-xs text-slate-500">
                Mağaza seçenekleri son Etsy senkronizasyonundan: {formatDate(options.fetchedAt)}
              </p>
              <DraftListingForm storeId={current.id} options={options} taxonomy={taxonomy} />
            </Card>
          )}
        </>
      )}
    </>
  );
}
