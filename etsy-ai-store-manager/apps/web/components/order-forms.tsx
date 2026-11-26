'use client';

import { useActionState } from 'react';
import {
  addMessageAction,
  messageAction,
  orderAction,
  slaAction,
  type OState,
} from '@/app/dashboard/orders/actions';

const input = 'w-full rounded-lg border border-line bg-white px-3 py-2 text-sm';
const btn =
  'rounded-lg bg-navy-900 px-3 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-60';
const ghost =
  'rounded-lg border border-line bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60';

function Fb({ s }: { s: OState }) {
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

export function TrackingForm({ storeId, orderId }: { storeId: string; orderId: string }) {
  const [s, action, pending] = useActionState<OState, FormData>(orderAction, {});
  return (
    <form action={action} className="grid gap-2 sm:grid-cols-2" aria-label="Takip numarası">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="orderId" value={orderId} />
      <input type="hidden" name="op" value="tracking" />
      <input
        name="trackingCode"
        required
        placeholder="Takip numarası"
        className={input}
        aria-label="Takip numarası"
      />
      <input
        name="carrierName"
        required
        placeholder="Kargo firması (ör. usps, ups, dhl)"
        className={input}
        aria-label="Kargo firması"
      />
      <input
        name="noteToBuyer"
        placeholder="Alıcıya not (isteğe bağlı)"
        className={`${input} sm:col-span-2`}
        aria-label="Alıcıya not"
      />
      <input name="reason" placeholder="Gerekçe" className={input} aria-label="Gerekçe" />
      <button className={btn} disabled={pending}>
        Onaya gönder
      </button>
      <div className="sm:col-span-2">
        <Fb s={s} />
      </div>
    </form>
  );
}

export function RefundForm({
  storeId,
  orderId,
  currency,
}: {
  storeId: string;
  orderId: string;
  currency: string;
}) {
  const [s, action, pending] = useActionState<OState, FormData>(orderAction, {});
  return (
    <form action={action} className="grid gap-2 sm:grid-cols-2" aria-label="İade">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="orderId" value={orderId} />
      <input type="hidden" name="op" value="refund" />
      <input
        name="amount"
        required
        inputMode="decimal"
        placeholder={`Tutar (${currency})`}
        className={input}
        aria-label="İade tutarı"
      />
      <input
        name="reason"
        required
        minLength={3}
        placeholder="Neden (ör. hasarlı ürün)"
        className={input}
        aria-label="İade nedeni"
      />
      <button className={ghost} disabled={pending}>
        İade onayı iste
      </button>
      <div className="sm:col-span-2">
        <Fb s={s} />
      </div>
    </form>
  );
}

export function CancelForm({ storeId, orderId }: { storeId: string; orderId: string }) {
  const [s, action, pending] = useActionState<OState, FormData>(orderAction, {});
  return (
    <form action={action} className="flex flex-wrap gap-2" aria-label="İptal">
      <input type="hidden" name="storeId" value={storeId} />
      <input type="hidden" name="orderId" value={orderId} />
      <input type="hidden" name="op" value="cancel" />
      <input
        name="reason"
        required
        minLength={3}
        placeholder="İptal nedeni"
        className="flex-1 rounded-lg border border-line px-3 py-2 text-sm"
        aria-label="İptal nedeni"
      />
      <button className={ghost} disabled={pending}>
        İptal onayı iste
      </button>
      <Fb s={s} />
    </form>
  );
}

export function SlaForm({
  storeId,
  processing,
  transit,
}: {
  storeId: string;
  processing: number;
  transit: number;
}) {
  const [s, action, pending] = useActionState<OState, FormData>(slaAction, {});
  return (
    <form action={action} className="flex flex-wrap items-end gap-2" aria-label="Gecikme eşikleri">
      <input type="hidden" name="storeId" value={storeId} />
      <label className="text-xs text-slate-600">
        En fazla hazırlık (gün)
        <input
          name="processing"
          type="number"
          min={1}
          max={60}
          defaultValue={processing}
          className={`${input} w-28`}
        />
      </label>
      <label className="text-xs text-slate-600">
        En fazla kargo (gün)
        <input
          name="transit"
          type="number"
          min={1}
          max={90}
          defaultValue={transit}
          className={`${input} w-28`}
        />
      </label>
      <button className={ghost} disabled={pending}>
        Kaydet
      </button>
      <Fb s={s} />
    </form>
  );
}

export function AddMessageForm({ storeId }: { storeId: string }) {
  const [s, action, pending] = useActionState<OState, FormData>(addMessageAction, {});
  return (
    <form action={action} className="space-y-2" aria-label="Mesaj ekle">
      <input type="hidden" name="storeId" value={storeId} />
      <textarea
        name="body"
        required
        rows={4}
        className={input}
        aria-label="Müşteri mesajı"
        placeholder="Etsy Mesajlar’dan müşterinin mesajını yapıştırın"
      />
      <div className="flex flex-wrap gap-2">
        <input
          name="receiptId"
          inputMode="numeric"
          placeholder="Sipariş no (isteğe bağlı)"
          className="rounded-lg border border-line px-3 py-2 text-sm"
          aria-label="Sipariş no"
        />
        <button className={btn} disabled={pending}>
          Kaydet ve taslak hazırla
        </button>
      </div>
      <Fb s={s} />
    </form>
  );
}

export interface Msg {
  id: string;
  source: string;
  rating: number | null;
  body: string;
  status: string;
  category: string | null;
  sentiment: string | null;
  urgency: string | null;
  issues: string[];
  suggestedAction: string | null;
  draft: string | null;
  draftLanguage: string | null;
  internalNote: string | null;
  aiError: string | null;
  etsyReceiptId: string | null;
  receivedAt: string | null;
}

const URG: Record<string, string> = {
  critical: 'bg-red-600 text-white',
  high: 'bg-red-100 text-red-800',
  normal: 'bg-slate-100 text-slate-700',
  low: 'bg-slate-50 text-slate-500',
};
const CAT: Record<string, string> = {
  question: 'Soru',
  complaint: 'Şikâyet',
  return: 'İade/değişim',
  shipping: 'Kargo',
  personalization: 'Kişiselleştirme',
  other: 'Diğer',
};
const ACTION: Record<string, string> = {
  reply: 'Yanıtla',
  refund: 'İade değerlendir',
  replacement: 'Yeniden gönderim değerlendir',
  shipping_check: 'Kargoyu kontrol et',
  personalization_fix: 'Kişiselleştirmeyi düzelt',
  none: 'İşlem gerekmez',
};

export function MessageCard({ storeId, m }: { storeId: string; m: Msg }) {
  const [s, action, pending] = useActionState<OState, FormData>(messageAction, {});
  const editable = ['draft_ready', 'new', 'failed'].includes(m.status);
  return (
    <article className="rounded-xl border border-line p-4" aria-label={`Mesaj ${m.id}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        {m.urgency && (
          <span className={`rounded-full px-2 py-0.5 font-semibold ${URG[m.urgency] ?? ''}`}>
            {m.urgency}
          </span>
        )}
        {m.category && (
          <span className="rounded bg-slate-100 px-1.5">{CAT[m.category] ?? m.category}</span>
        )}
        <span className="text-slate-500">
          {m.source === 'etsy_review' ? `Etsy yorumu ${m.rating}★ (herkese açık)` : 'Mesaj'}
        </span>
        {m.etsyReceiptId && <span className="text-slate-500">sipariş #{m.etsyReceiptId}</span>}
        <span data-testid="message-status" className="text-slate-500">
          {m.status}
        </span>
      </div>
      <blockquote className="whitespace-pre-line border-l-4 border-line pl-3 text-sm text-slate-800">
        {m.body}
      </blockquote>
      {m.internalNote && (
        <p className="mt-2 text-xs text-slate-700">
          AI notu: {m.internalNote}{' '}
          {m.suggestedAction ? `· Öneri: ${ACTION[m.suggestedAction] ?? m.suggestedAction}` : ''}
          {m.issues.length ? ` · ${m.issues.join(', ')}` : ''}
        </p>
      )}
      {m.aiError && <p className="mt-2 text-xs text-amber-800">{m.aiError}</p>}
      <form action={action} className="mt-3 space-y-2">
        <input type="hidden" name="storeId" value={storeId} />
        <input type="hidden" name="messageId" value={m.id} />
        {(m.draft || editable) && (
          <textarea
            name="text"
            defaultValue={m.draft ?? ''}
            rows={4}
            readOnly={!editable}
            className={input}
            aria-label="Yanıt taslağı"
          />
        )}
        {editable && (
          <div className="flex flex-wrap gap-2">
            <button name="op" value="send" className={btn} disabled={pending}>
              Yanıtı onaya gönder
            </button>
            <button name="op" value="triage" className={ghost} disabled={pending}>
              Yeniden taslak
            </button>
            <button name="op" value="close" className={ghost} disabled={pending}>
              Kapat
            </button>
          </div>
        )}
        <p className="text-xs text-slate-500">
          Taslak asla otomatik gönderilmez. İade, yeniden gönderim veya indirim sözü yalnızca ayrı
          onayla verilir.
        </p>
        <Fb s={s} />
      </form>
    </article>
  );
}
