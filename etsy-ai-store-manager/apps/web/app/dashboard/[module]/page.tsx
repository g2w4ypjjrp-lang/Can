import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { NAV_ITEMS } from '@esm/shared';
import { Card, Notice, PageHeader } from '@/components/ui';

type Params = { params: Promise<{ module: string }> };

function find(slug: string) {
  return NAV_ITEMS.find((n) => n.href === `/dashboard/${slug}`);
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const item = find((await params).module);
  return { title: item?.label ?? 'Modül' };
}

/**
 * Modules that are not implemented yet show their honest status. No placeholder
 * numbers or fake tables are rendered.
 */
export default async function ModulePage({ params }: Params) {
  const item = find((await params).module);
  if (!item) notFound();
  return (
    <>
      <PageHeader title={item.label} description={item.description} />
      <Card>
        <Notice>
          Bu modül <strong>FAZ {item.phase}</strong> kapsamında geliştirilecek. Şu an bu ekranda
          gösterilen herhangi bir veri yoktur; modül tamamlanana kadar örnek/sahte veri gösterilmez.
        </Notice>
        <p className="mt-4 text-sm text-slate-600" data-testid="module-status">
          Durum: {item.status === 'partial' ? 'Altyapı hazır, arayüz geliştiriliyor' : 'Planlandı'}
        </p>
      </Card>
    </>
  );
}
