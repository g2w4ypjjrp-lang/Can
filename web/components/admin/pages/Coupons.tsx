"use client";

import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { AdminCard, AdminPage, EmptyState, Feedback, StatusPill, Table, cell, inputClass, primaryButton, smallButton, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { dateTime, formatMinor, parseMoney } from "@/lib/admin";

interface Coupon {
  code: string;
  percent_off: number | null;
  amount_off_minor: number | null;
  currency: string | null;
  plan_codes: string[];
  max_redemptions: number | null;
  valid_from: string | null;
  valid_until: string | null;
  is_active: boolean;
  note: string;
  redemptions: number;
  discount_total_minor: number;
}

interface PlanOption {
  code: string;
  name: string;
}

function discountLabel(c: Coupon): string {
  return c.percent_off !== null ? `%${c.percent_off}` : `${formatMinor(c.amount_off_minor)} ${c.currency ?? ""}`;
}

function CouponRow({ coupon, onSaved }: { coupon: Coupon; onSaved: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const expired = coupon.valid_until !== null && new Date(coupon.valid_until) < new Date();
  const full = coupon.max_redemptions !== null && coupon.redemptions >= coupon.max_redemptions;

  async function toggle() {
    const ok = await action.run(() => api.patch(`/admin/v1/coupons/${coupon.code}`, { is_active: !coupon.is_active }));
    if (ok) onSaved();
  }

  return (
    <tr data-testid={`coupon-${coupon.code}`}>
      <td className={cell}>
        <p className="font-mono font-semibold">{coupon.code}</p>
        {coupon.note ? <p className="text-xs text-muted">{coupon.note}</p> : null}
      </td>
      <td className={cell}>{discountLabel(coupon)}</td>
      <td className={cell}>{coupon.plan_codes.length ? coupon.plan_codes.join(", ") : "Tüm ücretli paketler"}</td>
      <td className={cell}>
        {coupon.redemptions}
        {coupon.max_redemptions !== null ? ` / ${coupon.max_redemptions}` : ""}
        {coupon.discount_total_minor > 0 ? <p className="text-xs text-muted">Toplam indirim {formatMinor(coupon.discount_total_minor)}</p> : null}
      </td>
      <td className={cell}>
        {coupon.valid_from ? <p className="text-xs">Başlangıç: {dateTime(coupon.valid_from)}</p> : null}
        <p className="text-xs">{coupon.valid_until ? `Bitiş: ${dateTime(coupon.valid_until)}` : "Süresiz"}</p>
      </td>
      <td className={cell}>
        <StatusPill tone={!coupon.is_active || expired || full ? "neutral" : "success"} testId={`coupon-state-${coupon.code}`}>
          {!coupon.is_active ? "Kapalı" : expired ? "Süresi doldu" : full ? "Doldu" : "Geçerli"}
        </StatusPill>
      </td>
      <td className={cell}>
        <button type="button" className={smallButton} onClick={() => void toggle()} disabled={action.pending} aria-label={`${coupon.code} ${coupon.is_active ? "kapat" : "aç"}`}>
          {coupon.is_active ? "Kapat" : "Aç"}
        </button>
        <div className="mt-2 max-w-56">
          <Feedback error={action.error} />
        </div>
      </td>
    </tr>
  );
}

function CreateCoupon({ plans, onCreated }: { plans: PlanOption[]; onCreated: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [kind, setKind] = useState<"percent" | "amount">("percent");
  const [selected, setSelected] = useState<string[]>([]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const text = (name: string) => String(data.get(name) ?? "").trim();
    const body: Record<string, unknown> = { code: text("code").toUpperCase(), note: text("note"), plan_codes: selected };
    if (kind === "percent") {
      body.percent_off = Number(text("percent"));
    } else {
      const minor = parseMoney(text("amount"));
      if (minor === null) {
        await action.run(() => Promise.reject(new Error("Tutarı 250,00 biçiminde girin")));
        return;
      }
      body.amount_off_minor = minor;
      body.currency = text("currency");
    }
    if (text("max")) body.max_redemptions = Number(text("max"));
    if (text("until")) body.valid_until = new Date(`${text("until")}T23:59:59`).toISOString();
    const ok = await action.run(() => api.post("/admin/v1/coupons", body), "Kupon oluşturuldu");
    if (ok) {
      form.reset();
      setSelected([]);
      onCreated();
    }
  }

  return (
    <AdminCard title="Yeni kupon" description="Kodu müşteriyle paylaşın; ödeme sayfasındaki “Kupon kodu” alanına yazılır. Her müşteri bir kuponu bir kez kullanabilir.">
      <form onSubmit={(e) => void submit(e)} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <label className="block text-sm font-medium text-fg">
          Kod
          <input name="code" required pattern="[A-Za-z0-9][A-Za-z0-9\-]{2,31}" maxLength={32} placeholder="YENIYIL25" className={`mt-1 ${inputClass} font-mono uppercase`} />
        </label>
        <fieldset className="text-sm text-fg">
          <legend className="font-medium">İndirim türü</legend>
          <div className="mt-2 flex gap-4">
            <label className="flex items-center gap-2">
              <input type="radio" name="kind" checked={kind === "percent"} onChange={() => setKind("percent")} /> Yüzde
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="kind" checked={kind === "amount"} onChange={() => setKind("amount")} /> Tutar
            </label>
          </div>
        </fieldset>
        {kind === "percent" ? (
          <label className="block text-sm font-medium text-fg">
            İndirim (%)
            <input name="percent" type="number" min={1} max={100} required className={`mt-1 ${inputClass} w-28`} />
          </label>
        ) : (
          <div className="flex gap-2">
            <label className="block flex-1 text-sm font-medium text-fg">
              İndirim tutarı
              <input name="amount" required inputMode="decimal" placeholder="250,00" className={`mt-1 ${inputClass}`} />
            </label>
            <label className="block text-sm font-medium text-fg">
              Para birimi
              <select name="currency" className={`mt-1 ${inputClass} w-24`} defaultValue="TRY">
                {["TRY", "USD", "EUR"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
          </div>
        )}
        <label className="block text-sm font-medium text-fg">
          Kullanım sınırı <span className="font-normal text-muted">(boş = sınırsız)</span>
          <input name="max" type="number" min={1} className={`mt-1 ${inputClass} w-32`} />
        </label>
        <label className="block text-sm font-medium text-fg">
          Son geçerlilik günü <span className="font-normal text-muted">(boş = süresiz)</span>
          <input name="until" type="date" className={`mt-1 ${inputClass} w-44`} />
        </label>
        <label className="block text-sm font-medium text-fg">
          Not <span className="font-normal text-muted">(ör. kimin kodu)</span>
          <input name="note" maxLength={200} className={`mt-1 ${inputClass}`} />
        </label>
        <fieldset className="text-sm text-fg sm:col-span-2 lg:col-span-3">
          <legend className="font-medium">
            Geçerli paketler <span className="font-normal text-muted">(hiçbiri seçilmezse tüm ücretli paketler)</span>
          </legend>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
            {plans.map((p) => (
              <label key={p.code} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selected.includes(p.code)}
                  onChange={(e) => setSelected((s) => (e.target.checked ? [...s, p.code] : s.filter((c) => c !== p.code)))}
                />
                {p.name}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="sm:col-span-2 lg:col-span-3">
          <button type="submit" className={primaryButton} disabled={action.pending}>
            Kuponu oluştur
          </button>
          <div className="mt-3 max-w-xl">
            <Feedback error={action.error} message={action.message} />
          </div>
        </div>
      </form>
    </AdminCard>
  );
}

export function Coupons() {
  const coupons = useAdminQuery<Coupon[]>("/admin/v1/coupons");
  const plans = useAdminQuery<(PlanOption & { is_trial: boolean })[]>("/admin/v1/plans");
  return (
    <AdminPage
      title="İndirim kuponları"
      lead="Kampanya ve tanıtım kodları. Kişiye özel kod verip kaç satış getirdiğini buradan izleyebilirsiniz. Tutar her zaman sunucuda hesaplanır."
    >
      <CreateCoupon plans={(plans.data ?? []).filter((p) => !p.is_trial)} onCreated={coupons.reload} />
      <Feedback error={coupons.error ?? plans.error} />
      {coupons.data && coupons.data.length === 0 ? <EmptyState title="Henüz kupon yok">Yukarıdaki formla ilk kuponu oluşturun.</EmptyState> : null}
      {coupons.data && coupons.data.length > 0 ? (
        <Table caption="Kuponlar" head={["Kod", "İndirim", "Paketler", "Kullanım", "Geçerlilik", "Durum", ""]}>
          {coupons.data.map((c) => (
            <CouponRow key={c.code} coupon={c} onSaved={coupons.reload} />
          ))}
        </Table>
      ) : null}
    </AdminPage>
  );
}
