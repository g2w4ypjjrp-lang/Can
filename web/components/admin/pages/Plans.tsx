"use client";

import { useState } from "react";

import { useApi } from "@/components/ApiContext";
import { AdminPage, Feedback, Table, cell, inputClass, smallButton, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { durationLabel } from "@/lib/format";
import { formatMinor, parseMoney } from "@/lib/admin";

interface Plan {
  code: string;
  name: string;
  duration_days: number | null;
  device_limit: number;
  companion_device_limit: number;
  is_trial: boolean;
  price_minor: number | null;
  currency: string;
  is_active: boolean;
}

const CURRENCIES = ["TRY", "USD", "EUR"];

function PlanRow({ plan, onSaved }: { plan: Plan; onSaved: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [price, setPrice] = useState(formatMinor(plan.price_minor));
  const [currency, setCurrency] = useState(plan.currency);
  const [active, setActive] = useState(plan.is_active);
  const priceId = `fiyat-${plan.code}`;

  async function save() {
    const minor = price.trim() === "" ? null : parseMoney(price);
    if (price.trim() !== "" && minor === null) {
      action.setMessage(null);
      await action.run(() => Promise.reject(new Error("Fiyatı 1.499,90 biçiminde girin")));
      return;
    }
    const body: Record<string, unknown> = { currency, is_active: active };
    if (minor !== null) body.price_minor = minor;
    const ok = await action.run(() => api.patch(`/admin/v1/plans/${plan.code}`, body), "Kaydedildi");
    if (ok) onSaved();
  }

  return (
    <tr data-testid={`plan-${plan.code}`}>
      <td className={cell}>
        <p className="font-medium">{plan.name}</p>
        <p className="text-xs text-muted">
          {plan.code} · {durationLabel(plan.duration_days)} · {plan.device_limit} bilgisayar · {plan.companion_device_limit} telefon
        </p>
      </td>
      <td className={cell}>
        <label htmlFor={priceId} className="visually-hidden">
          {plan.name} fiyatı
        </label>
        <input id={priceId} value={price} onChange={(e) => setPrice(e.target.value)} placeholder="Fiyat yok" inputMode="decimal" className={`${inputClass} w-32`} />
      </td>
      <td className={cell}>
        <label htmlFor={`pb-${plan.code}`} className="visually-hidden">
          {plan.name} para birimi
        </label>
        <select id={`pb-${plan.code}`} value={currency} onChange={(e) => setCurrency(e.target.value)} className={`${inputClass} w-24`}>
          {CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </td>
      <td className={cell}>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4" />
          <span>Satışta</span>
        </label>
      </td>
      <td className={cell}>
        <button type="button" className={smallButton} onClick={() => void save()} disabled={action.pending} aria-label={`${plan.name} kaydet`}>
          Kaydet
        </button>
        <div className="mt-2 max-w-56">
          <Feedback error={action.error} message={action.message} />
        </div>
      </td>
    </tr>
  );
}

export function Plans() {
  const plans = useAdminQuery<Plan[]>("/admin/v1/plans");
  return (
    <AdminPage
      title="Paketler ve fiyatlar"
      lead="Fiyatı girilmemiş paket satışa açılamaz. Satıştaki paketler sitenin Paketler sayfasında hemen görünür."
    >
      <Feedback error={plans.error} />
      {plans.data ? (
        <Table caption="Lisans paketleri" head={["Paket", "Fiyat", "Para birimi", "Durum", ""]}>
          {plans.data.map((plan) => (
            <PlanRow key={plan.code} plan={plan} onSaved={plans.reload} />
          ))}
        </Table>
      ) : null}
    </AdminPage>
  );
}
