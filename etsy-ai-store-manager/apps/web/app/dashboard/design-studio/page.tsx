import type { Metadata } from 'next';
import Link from 'next/link';
import { api } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { CreateDesignForm } from '@/components/design-forms';

export const metadata: Metadata = { title: 'Tasarım Stüdyosu' };

interface Row {
  id: string;
  title: string;
  status: string;
  product_type: string | null;
  ip_risk_level: string;
  created_at: string;
  current_version_id: string | null;
  versions: number;
}

const RISK: Record<string, string> = {
  unknown: 'İncelenmedi',
  low: 'Düşük',
  medium: 'Orta',
  high: 'Yüksek',
};

export default async function DesignStudioPage({
  searchParams,
}: {
  searchParams: Promise<{ opportunity?: string }>;
}) {
  const sp = await searchParams;
  const { current } = await loadStores();
  if (!current) return <Notice>Önce mağaza kaydı oluşturun.</Notice>;
  const rows = await api<Row[]>(`/stores/${current.id}/designs`);
  const canAdmin = current.role === 'owner' || current.role === 'admin';
  let opp: { id: string; title: string; productType: string | null } | undefined;
  if (sp.opportunity && /^[0-9a-f-]{36}$/i.test(sp.opportunity)) {
    const list = await api<Array<{ id: string; title: string; productType: string | null }>>(
      `/stores/${current.id}/opportunities`,
    );
    opp = list.find((o) => o.id === sp.opportunity);
  }
  return (
    <>
      <PageHeader
        title="Tasarım Stüdyosu"
        description="Özgün tasarım: sizin yönlendirmeniz + AI (SVG) veya kendi dosyanız → IP kontrolü → baskı dosyası → Printify taslağı"
      />
      <Notice>
        AI tasarımları Claude ile vektör (SVG) olarak üretilir; tipografi, çizgi çizim ve grafik
        tasarımlar için uygundur. Fotoğraf gerçekliğinde görseller için kendi dosyanızı yükleyin.
        Etsy kuralları gereği AI kullanımını ilanda belirtin ve tasarıma kendi yaratıcı katkınızı
        ekleyin.
      </Notice>
      {canAdmin && (
        <Card title={opp ? `Fırsattan tasarım: ${opp.title}` : 'Yeni tasarım'} className="mt-6">
          <CreateDesignForm storeId={current.id} opportunity={opp} />
        </Card>
      )}
      <Card title={`Tasarımlar (${rows.length})`} className="mt-6">
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">Henüz tasarım yok.</p>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {rows.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/dashboard/design-studio/${d.id}`}
                  className="block rounded-xl border border-line p-3 hover:bg-slate-50"
                >
                  <div className="mb-2 flex aspect-[5/6] items-center justify-center overflow-hidden rounded-lg bg-[repeating-conic-gradient(#f1f5f9_0%_25%,#fff_0%_50%)] bg-[length:16px_16px]">
                    {d.current_version_id ? (
                      <img
                        src={`/files/designs/${d.id}/${d.current_version_id}`}
                        alt=""
                        className="max-h-full max-w-full object-contain"
                        loading="lazy"
                      />
                    ) : (
                      <span className="text-xs text-slate-400">görsel yok</span>
                    )}
                  </div>
                  <p className="truncate text-sm font-medium text-navy-900">{d.title}</p>
                  <p className="text-xs text-slate-500">
                    {d.product_type} · {d.status} · IP: {RISK[d.ip_risk_level] ?? d.ip_risk_level} ·{' '}
                    {d.versions} sürüm
                  </p>
                  <p className="text-xs text-slate-400">{formatDate(d.created_at)}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
