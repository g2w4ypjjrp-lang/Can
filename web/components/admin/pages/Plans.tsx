"use client";

import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { AdminCard, AdminPage, Feedback, StatusPill, Table, cell, inputClass, primaryButton, smallButton, useAdminAction, useAdminQuery } from "@/components/admin/kit";
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

interface Campaign {
  enabled: boolean;
  percent: number;
  label: string;
  ends_at: string | null;
  active: boolean;
}

/** ISO tarih → <input type="datetime-local"> değeri (tarayıcının yerel saatiyle). */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function CampaignForm({ campaign, onSaved }: { campaign: Campaign; onSaved: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [enabled, setEnabled] = useState(campaign.enabled);
  const [percent, setPercent] = useState(String(campaign.percent));

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const ends = String(data.get("ends_at") ?? "");
    const body = {
      enabled,
      percent: Number(percent),
      label: String(data.get("label") ?? "").trim(),
      ends_at: ends ? new Date(ends).toISOString() : null,
    };
    const ok = await action.run(() => api.put("/admin/v1/campaign", body), enabled ? "Kampanya kaydedildi" : "Kampanya kapatıldı");
    if (ok) onSaved();
  }

  const n = Number(percent);
  const sample = Number.isFinite(n) && n >= 1 && n <= 90 ? 1000 - Math.floor((1000 * n) / 100) : null;
  return (
    <form onSubmit={(e) => void save(e)} className="space-y-4" data-testid="campaign-form">
      <label className="flex items-center gap-2 text-sm font-medium text-fg">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="h-4 w-4" />
        Kampanya açık (bütün ücretli paketlere uygulanır)
      </label>
      <div className="grid gap-4 sm:grid-cols-[8rem_1fr_14rem]">
        <label className="text-sm text-fg">
          İndirim (%)
          <input
            name="percent"
            type="number"
            min={1}
            max={90}
            required
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
            className={`mt-1 ${inputClass}`}
          />
        </label>
        <label className="text-sm text-fg">
          Kampanya adı (sitede görünür, isteğe bağlı)
          <input name="label" maxLength={60} defaultValue={campaign.label} placeholder="Örn. Kasım indirimi" className={`mt-1 ${inputClass}`} />
        </label>
        <label className="text-sm text-fg">
          Bitiş (boş: siz kapatana kadar)
          <input name="ends_at" type="datetime-local" defaultValue={toLocalInput(campaign.ends_at)} className={`mt-1 ${inputClass}`} />
        </label>
      </div>
      {sample !== null ? (
        <p className="text-sm text-muted">
          Örnek: 1.000 ₺ olan paket {sample.toLocaleString("tr-TR")} ₺ olur. Müşteri kupon da kullanırsa kupon indirimli fiyatın üzerine
          uygulanır. Deneme paketi etkilenmez.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className={primaryButton} disabled={action.pending}>
          Kampanyayı kaydet
        </button>
        <Feedback error={action.error} message={action.message} />
      </div>
    </form>
  );
}

function CampaignCard() {
  const campaign = useAdminQuery<Campaign>("/admin/v1/campaign");
  const c = campaign.data;
  return (
    <AdminCard
      title="Genel indirim kampanyası"
      description="Yüzde indirim bütün ücretli paketlerin fiyatına uygulanır; sitede eski fiyat üstü çizili gösterilir."
      actions={
        c ? (
          <StatusPill tone={c.active ? "success" : "neutral"} testId="campaign-state">
            {c.active ? `Yayında · %${c.percent}` : c.enabled ? "Süresi doldu" : "Kapalı"}
          </StatusPill>
        ) : null
      }
    >
      <Feedback error={campaign.error} />
      {c ? <CampaignForm key={`${c.enabled}-${c.percent}-${c.label}-${c.ends_at}`} campaign={c} onSaved={campaign.reload} /> : null}
    </AdminCard>
  );
}

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
      {/* Aynı yetki (plan.manage): paketler yüklenemiyorsa yalnızca bir hata gösterilir. */}
      {plans.data ? <CampaignCard /> : null}
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
