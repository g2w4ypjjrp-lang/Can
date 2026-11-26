import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { api, ApiError } from '@/lib/api';
import { loadStores } from '@/lib/current-store';
import { formatDate } from '@/lib/format';
import { Card, Notice, PageHeader } from '@/components/ui';
import { DesignOps, PrintifyProductForm, UploadForm, VersionOps } from '@/components/design-forms';

export const metadata: Metadata = { title: 'Tasarım' };

interface Version {
  id: string;
  version: number;
  width_px: number;
  height_px: number;
  dpi: number;
  has_transparency: boolean;
  generator: string;
  operation: string;
  fit_report: { status: string; message: string; effectiveDpi: number } | null;
  print_area: { position: string; width: number; height: number } | null;
  created_at: string;
}
interface Detail {
  id: string;
  title: string;
  brief: string | null;
  humanContribution: string;
  productType: string | null;
  status: string;
  ipRiskLevel: string;
  ipRiskNotes: Array<{ issue: string; severity: string }>;
  ipReview: { recommendation?: string; textDetected?: string[] } | null;
  ipReviewedAt: string | null;
  currentVersionId: string | null;
  versions: Version[];
  products: Array<{ id: string; title: string; status: string }>;
}

const OPS: Record<string, string> = {
  upload: 'Yükleme',
  ai_generate: 'AI üretimi',
  remove_background: 'Arka plan kaldırıldı',
  prepare_print: 'Baskı dosyası',
};

export default async function DesignPage({ params }: { params: Promise<{ designId: string }> }) {
  const { designId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(designId)) notFound();
  const { current } = await loadStores();
  if (!current) notFound();
  let d: Detail;
  try {
    d = await api<Detail>(`/stores/${current.id}/designs/${designId}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const canAdmin = current.role === 'owner' || current.role === 'admin';
  return (
    <>
      <PageHeader
        title={d.title}
        description={`${d.productType ?? ''} · durum: ${d.status} · IP riski: ${d.ipRiskLevel}`}
      >
        <Link href="/dashboard/design-studio" className="text-sm text-brand-600 hover:underline">
          ← Tasarımlar
        </Link>
      </PageHeader>
      <div className="mb-4 space-y-2">
        {d.ipRiskLevel === 'high' && (
          <Notice tone="warn">
            Yüksek fikri mülkiyet riski: {d.ipRiskNotes.map((n) => n.issue).join(' · ')}. Bu tasarım
            onaylanamaz.
          </Notice>
        )}
        {d.ipReview?.recommendation && (
          <Notice>
            AI IP incelemesi ({formatDate(d.ipReviewedAt)}): {d.ipReview.recommendation} — hukuki
            görüş değildir.
          </Notice>
        )}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Yaratıcı yönlendirme" className="lg:col-span-2">
          <p className="text-sm text-slate-800" data-testid="human-contribution">
            {d.humanContribution}
          </p>
          {d.brief && <p className="mt-2 text-sm text-slate-600">Özet: {d.brief}</p>}
          <div className="mt-4 space-y-3">
            <DesignOps
              storeId={current.id}
              designId={d.id}
              canAdmin={canAdmin}
              hasVersion={Boolean(d.currentVersionId)}
              canGenerate={Boolean(d.brief) && d.ipRiskLevel !== 'high'}
            />
            {canAdmin && <UploadForm storeId={current.id} designId={d.id} />}
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Onay için: IP incelemesi (güncel görsel), yüksek risk olmaması ve baskıya hazır sürüm
            gerekir.
          </p>
        </Card>
        <Card title="Printify ürünü">
          {d.products.length > 0 && (
            <ul className="mb-3 space-y-1 text-sm">
              {d.products.map((p) => (
                <li key={p.id}>
                  <Link
                    href={`/dashboard/products/${p.id}`}
                    className="text-brand-600 hover:underline"
                  >
                    {p.title}
                  </Link>{' '}
                  · {p.status}
                </li>
              ))}
            </ul>
          )}
          {d.status === 'approved' && canAdmin ? (
            <PrintifyProductForm storeId={current.id} designId={d.id} defaultTitle={d.title} />
          ) : (
            <p className="text-sm text-slate-500">
              Tasarım onaylandıktan sonra taslak ürün oluşturulabilir.
            </p>
          )}
        </Card>
      </div>
      <Card title={`Sürümler (${d.versions.length})`} className="mt-6">
        {d.versions.length === 0 ? (
          <p className="text-sm text-slate-500">
            Henüz görsel yok: AI ile üretin veya dosya yükleyin.
          </p>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Sürümler">
            {d.versions.map((v) => (
              <li
                key={v.id}
                className={`rounded-xl border p-3 ${v.id === d.currentVersionId ? 'border-brand-500' : 'border-line'}`}
              >
                <div className="mb-2 flex aspect-[5/6] items-center justify-center overflow-hidden rounded-lg bg-[repeating-conic-gradient(#f1f5f9_0%_25%,#fff_0%_50%)] bg-[length:16px_16px]">
                  <img
                    src={`/files/designs/${d.id}/${v.id}`}
                    alt={`Sürüm ${v.version}`}
                    className="max-h-full max-w-full object-contain"
                    loading="lazy"
                  />
                </div>
                <p className="text-sm font-medium">
                  v{v.version} · {OPS[v.operation] ?? v.operation}
                </p>
                <p className="text-xs text-slate-500">
                  {v.width_px}×{v.height_px} px · {v.dpi} DPI ·{' '}
                  {v.has_transparency ? 'şeffaf' : 'opak'}
                </p>
                {v.fit_report && (
                  <p
                    className={`mt-1 text-xs ${v.fit_report.status === 'ok' ? 'text-emerald-700' : 'text-amber-800'}`}
                  >
                    {v.print_area?.position}: {v.fit_report.message}
                  </p>
                )}
                {canAdmin && <VersionOps storeId={current.id} designId={d.id} versionId={v.id} />}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
