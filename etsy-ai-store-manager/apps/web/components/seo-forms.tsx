'use client';

import { useActionState } from 'react';
import {
  checkAction,
  draftAction,
  draftListingAction,
  requestSeoAction,
  translateAction,
  translationAction,
  type SState,
} from '@/app/dashboard/seo/actions';

const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';
const label = 'mb-1 block text-xs font-medium text-slate-600';
const btn =
  'rounded-lg bg-navy-900 px-3 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60';
const ghost =
  'rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60';

export interface Issue {
  field: string;
  code?: string;
  severity: string;
  message: string;
}
export interface SeoDraft {
  id: string;
  language: string;
  status: string;
  primaryKeyword: string | null;
  title: string | null;
  description: string | null;
  tags: string[];
  materials: string[];
  rationale: string | null;
  seoScore: number | null;
  issues: Issue[];
  baseline: { title?: string; description?: string | null; tags?: string[] };
  source: string;
  error: string | null;
  costUsd: string | null;
  createdAt: string;
}
export interface Translation {
  id: string;
  language: string;
  status: string;
  title: string | null;
  description: string | null;
  tags: string[];
  qualityScore: number | null;
  qualityNotes: Issue[];
  backTranslation: { title: string; description: string } | null;
  localizationNotes: string[];
  publishedAt: string | null;
  error: string | null;
}

function Fb({ s }: { s: SState }) {
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

const SEV: Record<string, string> = {
  error: 'text-red-700',
  warning: 'text-amber-800',
  info: 'text-slate-500',
};
const SEV_LABEL: Record<string, string> = { error: 'Hata', warning: 'Uyarı', info: 'Bilgi' };

export function IssueList({ issues }: { issues: Issue[] }) {
  if (!issues.length)
    return <p className="text-xs text-emerald-700">Etsy kural ve spam kontrolünden geçti.</p>;
  return (
    <ul className="space-y-0.5 text-xs" aria-label="Kontrol sonuçları">
      {issues.map((i, n) => (
        <li key={n} className={SEV[i.severity] ?? ''}>
          [{SEV_LABEL[i.severity] ?? i.severity}] {i.message}
        </li>
      ))}
    </ul>
  );
}

function Score({ v }: { v: number | null }) {
  if (v === null) return null;
  const tone =
    v >= 80
      ? 'bg-emerald-100 text-emerald-800'
      : v >= 50
        ? 'bg-amber-100 text-amber-900'
        : 'bg-red-100 text-red-800';
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${tone}`}>{v}/100</span>;
}

export function RequestSeoForm({
  storeId,
  target,
  languages,
  path,
}: {
  storeId: string;
  target: { listingId?: string; productId?: string };
  languages: string[];
  path: string;
}) {
  const [s, action, pending] = useActionState<SState, FormData>(requestSeoAction, {});
  return (
    <form
      action={action}
      className="flex flex-wrap items-center gap-2"
      aria-label="SEO önerisi iste"
    >
      <input type="hidden" name="storeId" value={storeId} />
      {target.listingId && <input type="hidden" name="listingId" value={target.listingId} />}
      {target.productId && <input type="hidden" name="productId" value={target.productId} />}
      <input type="hidden" name="path" value={path} />
      <select
        name="language"
        className="rounded-lg border border-line px-2 py-2 text-sm"
        aria-label="Dil"
      >
        {languages.map((l) => (
          <option key={l}>{l}</option>
        ))}
      </select>
      <button className={btn} disabled={pending}>
        {pending ? 'Başlatılıyor…' : 'AI SEO önerisi hazırla'}
      </button>
      <Fb s={s} />
    </form>
  );
}

export function SeoDraftCard({
  storeId,
  d,
  canEdit,
  path,
}: {
  storeId: string;
  d: SeoDraft;
  canEdit: boolean;
  path: string;
}) {
  const [s, action, pending] = useActionState<SState, FormData>(draftAction, {});
  const editable =
    canEdit && ['draft', 'rejected', 'failed'].includes(d.status) && d.title !== null;
  return (
    <article className="rounded-xl border border-line p-4" aria-label={`SEO önerisi ${d.language}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="font-semibold uppercase text-navy-900">{d.language}</span>
        <span data-testid="seo-status">{d.status}</span>
        <Score v={d.seoScore} />
        {d.primaryKeyword && <span>ana ifade: “{d.primaryKeyword}”</span>}
        <span>{d.source === 'manual' ? 'elle düzenlendi' : 'AI'}</span>
        {d.costUsd && <span>AI maliyeti ${Number(d.costUsd).toFixed(4)}</span>}
      </div>
      {d.status === 'generating' && <p className="text-sm text-slate-500">Hazırlanıyor…</p>}
      {d.error && <p className="mb-2 text-sm text-amber-800">{d.error}</p>}
      {d.title !== null && (
        <form action={action} className="space-y-2">
          <input type="hidden" name="storeId" value={storeId} />
          <input type="hidden" name="draftId" value={d.id} />
          <input type="hidden" name="path" value={path} />
          <label className="block">
            <span className={label}>
              Başlık ({d.title.length}/140) — şu an: {d.baseline.title}
            </span>
            <input
              name="title"
              defaultValue={d.title}
              maxLength={140}
              className={input}
              readOnly={!editable}
            />
          </label>
          <label className="block">
            <span className={label}>Etiketler ({d.tags.length}/13, virgülle)</span>
            <textarea
              name="tags"
              defaultValue={d.tags.join(', ')}
              rows={2}
              className={input}
              readOnly={!editable}
            />
          </label>
          <label className="block">
            <span className={label}>Açıklama</span>
            <textarea
              name="description"
              defaultValue={d.description ?? ''}
              rows={6}
              className={input}
              readOnly={!editable}
            />
          </label>
          {d.materials.length > 0 && (
            <label className="block">
              <span className={label}>Malzemeler</span>
              <input
                name="materials"
                defaultValue={d.materials.join(', ')}
                className={input}
                readOnly={!editable}
              />
            </label>
          )}
          {d.rationale && <p className="text-xs text-slate-600">Gerekçe: {d.rationale}</p>}
          <IssueList issues={d.issues} />
          {editable && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <input
                name="reason"
                placeholder="Onay gerekçesi"
                className="rounded-lg border border-line px-2 py-2 text-sm"
                aria-label="Gerekçe"
              />
              <button name="op" value="save" className={ghost} disabled={pending}>
                Kaydet ve kontrol et
              </button>
              <button name="op" value="apply" className={btn} disabled={pending}>
                Uygulamak için onaya gönder
              </button>
              <button name="op" value="reject" className={ghost} disabled={pending}>
                Reddet
              </button>
            </div>
          )}
          <Fb s={s} />
        </form>
      )}
    </article>
  );
}

export function TranslateForm({
  storeId,
  listingId,
  languages,
  path,
}: {
  storeId: string;
  listingId: string;
  languages: string[];
  path: string;
}) {
  const [s, action, pending] = useActionState<SState, FormData>(translateAction, {});
  if (!languages.length)
    return (
      <p className="text-sm text-slate-500">
        Ek dil yok. Ayarlar → Mağaza dillerinden dil ekleyin.
      </p>
    );
  return (
    <form action={action} className="flex flex-wrap items-center gap-3" aria-label="Çeviri iste">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="listingId" value={listingId} />
      <input type="hidden" name="path" value={path} />
      {languages.map((l) => (
        <label key={l} className="flex items-center gap-1 text-sm">
          <input type="checkbox" name="languages" value={l} className="h-4 w-4 accent-brand-600" />{' '}
          {l}
        </label>
      ))}
      <button className={btn} disabled={pending}>
        {pending ? 'Başlatılıyor…' : 'AI ile yerelleştir'}
      </button>
      <Fb s={s} />
    </form>
  );
}

export function TranslationCard({
  storeId,
  t,
  canEdit,
  path,
}: {
  storeId: string;
  t: Translation;
  canEdit: boolean;
  path: string;
}) {
  const [s, action, pending] = useActionState<SState, FormData>(translationAction, {});
  const editable =
    canEdit && !['generating', 'pending_approval'].includes(t.status) && t.title !== null;
  return (
    <article className="rounded-xl border border-line p-4" aria-label={`Çeviri ${t.language}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="font-semibold uppercase text-navy-900">{t.language}</span>
        <span data-testid="translation-status">{t.status}</span>
        <Score v={t.qualityScore} />
        {t.publishedAt && <span>Etsy’de yayında</span>}
      </div>
      {t.status === 'generating' && <p className="text-sm text-slate-500">Hazırlanıyor…</p>}
      {t.error && <p className="mb-2 text-sm text-amber-800">{t.error}</p>}
      {t.title !== null && (
        <form action={action} className="space-y-2">
          <input type="hidden" name="storeId" value={storeId} />
          <input type="hidden" name="translationId" value={t.id} />
          <input type="hidden" name="path" value={path} />
          <input
            name="title"
            defaultValue={t.title}
            maxLength={140}
            className={input}
            readOnly={!editable}
            aria-label="Çeviri başlığı"
          />
          <textarea
            name="tags"
            defaultValue={t.tags.join(', ')}
            rows={2}
            className={input}
            readOnly={!editable}
            aria-label="Çeviri etiketleri"
          />
          <textarea
            name="description"
            defaultValue={t.description ?? ''}
            rows={5}
            className={input}
            readOnly={!editable}
            aria-label="Çeviri açıklaması"
          />
          {t.backTranslation && (
            <div className="rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
              <p className="font-semibold">Geri çeviri (kontrol için, İngilizce)</p>
              <p>{t.backTranslation.title}</p>
              <p className="mt-1 whitespace-pre-line">{t.backTranslation.description}</p>
            </div>
          )}
          {t.localizationNotes.length > 0 && (
            <ul className="text-xs text-slate-600">
              {t.localizationNotes.map((n, i) => (
                <li key={i}>• {n}</li>
              ))}
            </ul>
          )}
          <IssueList issues={t.qualityNotes} />
          {editable && (
            <div className="flex flex-wrap items-center gap-2">
              <button name="op" value="save" className={ghost} disabled={pending}>
                Kaydet
              </button>
              {t.status !== 'reviewed' && (
                <button name="op" value="review" className={ghost} disabled={pending}>
                  İnceledim, doğru
                </button>
              )}
              {t.status === 'reviewed' && (
                <>
                  <input
                    name="reason"
                    placeholder="Onay gerekçesi"
                    className="rounded-lg border border-line px-2 py-2 text-sm"
                    aria-label="Gerekçe"
                  />
                  <button name="op" value="publish" className={btn} disabled={pending}>
                    Etsy’ye eklemek için onaya gönder
                  </button>
                </>
              )}
              <button name="op" value="reject" className={ghost} disabled={pending}>
                Reddet
              </button>
            </div>
          )}
          <Fb s={s} />
        </form>
      )}
    </article>
  );
}

export function SeoCheckForm({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<SState, FormData>(checkAction, {});
  return (
    <form action={action} className="space-y-2" aria-label="Kural kontrolü">
      <input type="hidden" name="storeId" value={storeId} />
      <input
        name="title"
        required
        maxLength={140}
        placeholder="Başlık"
        className={input}
        aria-label="Başlık"
      />
      <input
        name="primaryKeyword"
        placeholder="Ana arama ifadesi (isteğe bağlı)"
        className={input}
        aria-label="Ana ifade"
      />
      <textarea
        name="tags"
        rows={2}
        placeholder="Etiketler (virgülle)"
        className={input}
        aria-label="Etiketler"
      />
      <textarea
        name="description"
        required
        rows={4}
        placeholder="Açıklama"
        className={input}
        aria-label="Açıklama"
      />
      <button className={ghost} disabled={pending}>
        Kontrol et
      </button>
      {s.check && (
        <div className="space-y-1" data-testid="seo-check">
          <p className="text-sm">
            Puan <Score v={s.check.score} />{' '}
            {s.check.blocking ? '— Etsy’ye gönderilemez' : '— gönderilebilir'}
          </p>
          <IssueList issues={s.check.issues} />
        </div>
      )}
      <Fb s={s} />
    </form>
  );
}

export interface ListingOptions {
  connected: boolean;
  shippingProfiles: Array<{ id: number; title: string }>;
  returnPolicies: Array<{ id: number; acceptsReturns: boolean; deadlineDays: number | null }>;
  productionPartners: Array<{ id: number; name: string; location: string }>;
  fetchedAt: string | null;
}

export function DraftListingForm({
  storeId,
  options,
  taxonomy,
}: {
  storeId: string;
  options: ListingOptions;
  taxonomy: Array<{ id: number; path: string; leaf: boolean }>;
}) {
  const [s, action, pending] = useActionState<SState, FormData>(draftListingAction, {});
  return (
    <form action={action} className="grid gap-3 sm:grid-cols-2" aria-label="Etsy taslak ilan">
      <input type="hidden" name="storeId" value={storeId} />
      <label className="sm:col-span-2">
        <span className={label}>Başlık (en fazla 140)</span>
        <input name="title" required maxLength={140} className={input} />
      </label>
      <label className="sm:col-span-2">
        <span className={label}>Açıklama</span>
        <textarea name="description" required rows={5} className={input} />
      </label>
      <label>
        <span className={label}>Etiketler (virgülle, en fazla 13)</span>
        <textarea name="tags" rows={2} className={input} />
      </label>
      <label>
        <span className={label}>Malzemeler (virgülle)</span>
        <textarea name="materials" rows={2} className={input} />
      </label>
      <label>
        <span className={label}>Fiyat (USD)</span>
        <input name="price" required inputMode="decimal" placeholder="28.99" className={input} />
      </label>
      <label>
        <span className={label}>Adet</span>
        <input
          name="quantity"
          required
          type="number"
          min={1}
          max={999}
          defaultValue={10}
          className={input}
        />
      </label>
      <label className="sm:col-span-2">
        <span className={label}>Kategori</span>
        <select name="taxonomyId" required className={input}>
          {taxonomy
            .filter((t) => t.leaf)
            .map((t) => (
              <option key={t.id} value={t.id}>
                {t.path}
              </option>
            ))}
        </select>
      </label>
      <label>
        <span className={label}>Kim yaptı</span>
        <select name="whoMade" className={input} defaultValue="i_did">
          <option value="i_did">Ben (tasarım benim; üretim ortağıyla)</option>
          <option value="collective">Ekibim</option>
          <option value="someone_else">Başkası (yalnız malzeme/vintage)</option>
        </select>
      </label>
      <label>
        <span className={label}>Ne zaman yapıldı</span>
        <select name="whenMade" className={input} defaultValue="made_to_order">
          <option value="made_to_order">Siparişe göre üretilir</option>
          <option value="2020_2026">2020–2026</option>
          <option value="2010_2019">2010–2019</option>
          <option value="before_2007">2007 öncesi</option>
        </select>
      </label>
      <label>
        <span className={label}>Kargo profili (zorunlu)</span>
        <select name="shippingProfileId" required className={input}>
          {options.shippingProfiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className={label}>İade politikası</span>
        <select name="returnPolicyId" className={input}>
          <option value="">—</option>
          {options.returnPolicies.map((p) => (
            <option key={p.id} value={p.id}>
              {p.acceptsReturns ? `İade ${p.deadlineDays ?? '?'} gün` : 'İade yok'}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="sm:col-span-2">
        <legend className={label}>
          Üretim ortakları (Etsy, üretim ortağıyla yapılan ürünlerde beyan ister)
        </legend>
        <div className="flex flex-wrap gap-3">
          {options.productionPartners.map((p) => (
            <label key={p.id} className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                name="productionPartnerIds"
                value={p.id}
                defaultChecked
                className="h-4 w-4 accent-brand-600"
              />
              {p.name} ({p.location})
            </label>
          ))}
          {options.productionPartners.length === 0 && (
            <span className="text-xs text-slate-500">Etsy’de tanımlı üretim ortağı yok.</span>
          )}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="isSupply" className="h-4 w-4 accent-brand-600" /> Malzeme
        (supply) ürünü
      </label>
      <label>
        <span className={label}>Onay gerekçesi</span>
        <input name="reason" className={input} placeholder="Yeni ürün" />
      </label>
      <div className="flex items-center gap-3 sm:col-span-2">
        <button className={btn} disabled={pending || !options.shippingProfiles.length}>
          Taslak ilan için onaya gönder
        </button>
        <Fb s={s} />
      </div>
    </form>
  );
}
