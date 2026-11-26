import type { Metadata } from 'next';
import Link from 'next/link';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { SeoCheckForm, type SeoDraft } from '@/components/seo-forms';

export const metadata: Metadata = { title: 'SEO Merkezi' };

type Row = SeoDraft & { listingId: string | null; productId: string | null };

const STATUS: Record<string, string> = {
  generating: 'Hazırlanıyor',
  draft: 'Taslak',
  pending_approval: 'Onay bekliyor',
  applied: 'Uygulandı',
  rejected: 'Reddedildi',
  failed: 'Hata',
};

export default async function SeoPage() {
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const drafts = await api<Row[]>(`/stores/${current.id}/seo-drafts`);
  const canEdit = current.role === 'owner' || current.role === 'admin';
  return (
    <>
      <PageHeader
        title="SEO Merkezi"
        description="Başlık, açıklama, 13 etiket ve çok dilli içerik; Etsy kural ve spam kontrolüyle"
      >
        {canEdit && (
          <Link
            href="/dashboard/seo/new-listing"
            className="rounded-lg bg-navy-900 px-3 py-2 text-sm font-semibold text-white"
          >
            Yeni Etsy taslak ilanı
          </Link>
        )}
      </PageHeader>
      <Notice>
        SEO önerisi bir ilan (Etsy İlanlarım → ilan) veya Printify ürünü sayfasından istenir. Hiçbir
        değişiklik onaysız Etsy’ye ya da Printify’a gönderilmez. Çeviriler ilan sayfasındaki
        “Diller” bölümündedir.
      </Notice>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title={`Son öneriler (${drafts.length})`} className="lg:col-span-2">
          {drafts.length === 0 ? (
            <p className="text-sm text-slate-500">Henüz öneri yok.</p>
          ) : (
            <table className="w-full text-left text-sm" aria-label="SEO önerileri">
              <thead className="border-b border-line text-xs uppercase text-slate-500">
                <tr>
                  <th className="py-2 pr-3">Başlık</th>
                  <th className="py-2 pr-3">Dil</th>
                  <th className="py-2 pr-3">Puan</th>
                  <th className="py-2 pr-3">Durum</th>
                  <th className="py-2">Tarih</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {drafts.map((d) => (
                  <tr key={d.id}>
                    <td className="py-2 pr-3">
                      <Link
                        href={
                          d.listingId
                            ? `/dashboard/etsy/listings/${d.listingId}`
                            : `/dashboard/products/${d.productId}`
                        }
                        className="text-brand-600 hover:underline"
                      >
                        {(d.title ?? d.baseline.title ?? '—').slice(0, 70)}
                      </Link>
                    </td>
                    <td className="py-2 pr-3 uppercase">{d.language}</td>
                    <td className="py-2 pr-3 tabular-nums">{d.seoScore ?? '—'}</td>
                    <td className="py-2 pr-3">{STATUS[d.status] ?? d.status}</td>
                    <td className="py-2 text-slate-500">{formatDate(d.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Kural kontrolü (AI yok)">
          <SeoCheckForm storeId={current.id} />
        </Card>
      </div>
    </>
  );
}
