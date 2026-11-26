'use client';

import { useActionState } from 'react';
import {
  createDesignAction,
  createPrintifyProductAction,
  designOpAction,
  uploadDesignAction,
  type DState,
} from '@/app/dashboard/design-studio/actions';

const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';
const label = 'mb-1 block text-sm font-medium text-slate-700';
const btn =
  'rounded-lg bg-navy-900 px-3 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60';
const ghost =
  'rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60';

function Fb({ s }: { s: DState }) {
  if (s.error)
    return (
      <p role="alert" className="text-sm text-red-700">
        {s.error}
      </p>
    );
  if (s.info)
    return (
      <p role="status" className="text-sm text-emerald-700">
        {s.info}
      </p>
    );
  return null;
}

const PRODUCT_TYPES = [
  'T-Shirt',
  'Sweatshirt',
  'Hoodie',
  'Poster',
  'Canvas',
  'Mug',
  'Tote Bag',
  'Phone Case',
  'Pillow',
  'Blanket',
  'Sticker',
];

export function CreateDesignForm({
  storeId,
  opportunity,
}: {
  storeId: string;
  opportunity?: { id: string; title: string; productType: string | null };
}) {
  const [s, action, pending] = useActionState<DState, FormData>(createDesignAction, {});
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-2" aria-label="Yeni tasarım">
      <input type="hidden" name="storeId" value={storeId} />
      {opportunity && <input type="hidden" name="opportunityId" value={opportunity.id} />}
      <label>
        <span className={label}>Başlık</span>
        <input name="title" required defaultValue={opportunity?.title ?? ''} className={input} />
      </label>
      <label>
        <span className={label}>Ürün tipi</span>
        <select
          name="productType"
          defaultValue={opportunity?.productType ?? 'T-Shirt'}
          className={input}
        >
          {PRODUCT_TYPES.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </label>
      <label className="sm:col-span-2">
        <span className={label}>Tasarım özeti (AI üretimi için; İngilizce önerilir)</span>
        <textarea
          name="brief"
          rows={2}
          className={input}
          placeholder="ör. Minimal botanical typography about patience for plant lovers"
        />
      </label>
      <label className="sm:col-span-2">
        <span className={label}>Sizin yaratıcı yönlendirmeniz (zorunlu, en az 20 karakter)</span>
        <textarea
          name="humanContribution"
          required
          minLength={20}
          rows={3}
          className={input}
          placeholder="Kompozisyon, metin, renkler, his: tasarımın sizin fikriniz olduğunu gösteren yönlendirme"
        />
        <span className="mt-1 block text-xs text-slate-500">
          Etsy, AI ile üretilen ürünlerde satıcının yaratıcı katkısını ve doğru beyanı ister; bu
          metin kayıt altına alınır.
        </span>
      </label>
      <label className="sm:col-span-2">
        <span className={label}>Stil (isteğe bağlı)</span>
        <input name="style" className={input} placeholder="ör. hand-drawn line art, two colours" />
      </label>
      <div className="flex items-center gap-3 sm:col-span-2">
        <button className={btn} disabled={pending}>
          {pending ? 'Oluşturuluyor…' : 'Tasarım oluştur'}
        </button>
        <Fb s={s} />
      </div>
    </form>
  );
}

export function DesignOps({
  storeId,
  designId,
  canAdmin,
  hasVersion,
  canGenerate,
}: {
  storeId: string;
  designId: string;
  canAdmin: boolean;
  hasVersion: boolean;
  canGenerate: boolean;
}) {
  const [s, action, pending] = useActionState<DState, FormData>(designOpAction, {});
  if (!canAdmin) return null;
  return (
    <form
      action={action}
      className="flex flex-wrap items-center gap-2"
      aria-label="Tasarım işlemleri"
    >
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="designId" value={designId} />
      {canGenerate && (
        <button name="op" value="generate" className={btn} disabled={pending}>
          AI ile tasarım üret
        </button>
      )}
      {hasVersion && (
        <button name="op" value="ip-review" className={ghost} disabled={pending}>
          IP incelemesi yap
        </button>
      )}
      <button name="op" value="approve" className={ghost} disabled={pending}>
        Onayla
      </button>
      <button name="op" value="reject" className={ghost} disabled={pending}>
        Reddet
      </button>
      <Fb s={s} />
    </form>
  );
}

export function UploadForm({ storeId, designId }: { storeId: string; designId: string }) {
  const [s, action, pending] = useActionState<DState, FormData>(uploadDesignAction, {});
  return (
    <form action={action} className="flex flex-wrap items-center gap-2" aria-label="Görsel yükle">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="designId" value={designId} />
      <input
        type="file"
        name="file"
        accept="image/png,image/jpeg,image/webp,image/svg+xml"
        className="text-sm"
        aria-label="Dosya"
      />
      <button className={ghost} disabled={pending}>
        {pending ? 'Yükleniyor…' : 'Yükle'}
      </button>
      <Fb s={s} />
    </form>
  );
}

export function VersionOps({
  storeId,
  designId,
  versionId,
}: {
  storeId: string;
  designId: string;
  versionId: string;
}) {
  const [s, action, pending] = useActionState<DState, FormData>(designOpAction, {});
  return (
    <form action={action} className="mt-2 space-y-2" aria-label={`Sürüm işlemleri ${versionId}`}>
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="designId" value={designId} />
      <input type="hidden" name="versionId" value={versionId} />
      <div className="grid grid-cols-3 gap-1">
        <input
          name="blueprintId"
          placeholder="Blueprint"
          defaultValue="6"
          className="rounded border border-line px-2 py-1 text-xs"
          aria-label="Blueprint ID"
        />
        <input
          name="printProviderId"
          placeholder="Sağlayıcı"
          defaultValue="29"
          className="rounded border border-line px-2 py-1 text-xs"
          aria-label="Sağlayıcı ID"
        />
        <input
          name="position"
          placeholder="front"
          defaultValue="front"
          className="rounded border border-line px-2 py-1 text-xs"
          aria-label="Baskı alanı"
        />
      </div>
      <div className="flex flex-wrap gap-1">
        <button
          name="op"
          value="prepare-print"
          className="rounded border border-line px-2 py-1 text-xs"
          disabled={pending}
        >
          Baskıya hazırla
        </button>
        <button
          name="op"
          value="remove-background"
          className="rounded border border-line px-2 py-1 text-xs"
          disabled={pending}
        >
          Arka planı kaldır
        </button>
      </div>
      <Fb s={s} />
    </form>
  );
}

export function PrintifyProductForm({
  storeId,
  designId,
  defaultTitle,
}: {
  storeId: string;
  designId: string;
  defaultTitle: string;
}) {
  const [s, action, pending] = useActionState<DState, FormData>(createPrintifyProductAction, {});
  return (
    <form action={action} className="grid gap-2" aria-label="Printify ürünü oluştur">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="designId" value={designId} />
      <label>
        <span className={label}>Ürün başlığı</span>
        <input name="title" defaultValue={defaultTitle} className={input} />
      </label>
      <label>
        <span className={label}>Açıklama</span>
        <textarea name="description" rows={3} className={input} />
      </label>
      <label>
        <span className={label}>Printify varyant ID’leri (virgülle)</span>
        <input name="variantIds" className={input} placeholder="12100, 12101" />
      </label>
      <label>
        <span className={label}>Satış fiyatı (USD)</span>
        <input name="priceUsd" inputMode="decimal" className={input} placeholder="28.99" />
      </label>
      <button className={btn} disabled={pending}>
        Printify’da taslak ürün oluştur
      </button>
      <p className="text-xs text-slate-500">
        Taslak Etsy’ye gönderilmez. Yayın için ürün sayfasından kâr kontrollü onay isteği
        oluşturulur.
      </p>
      <Fb s={s} />
    </form>
  );
}
