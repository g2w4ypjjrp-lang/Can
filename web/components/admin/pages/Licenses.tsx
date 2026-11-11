"use client";

import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, Table, TotpInput, cell, inputClass, smallButton, useAdminAction, useAdminQuery, StatusPill, licenseTone } from "@/components/admin/kit";
import { Button, Card } from "@/components/ui";
import { can, dateTime, toCsv } from "@/lib/admin";
import { licenseStatusLabel } from "@/lib/format";

interface LicenseRow {
  id: string;
  serial: number;
  key_hint: string;
  plan_code: string;
  status: string;
  expires_at: string | null;
  customer_email: string | null;
  active_devices: number;
  device_limit: number;
}

interface LicenseDetail extends LicenseRow {
  frozen_reason: string | null;
  cancel_reason: string | null;
  events: { from_status: string | null; to_status: string; actor_type: string; occurred_at: string }[];
  activations: { device_id: string; display_name: string; activated_at: string; deactivated_at: string | null }[];
}

interface PlanLite {
  code: string;
  name: string;
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const api = useApi();
  const { me } = useAdmin();
  const detail = useAdminQuery<LicenseDetail>(`/admin/v1/licenses/${id}`);
  const action = useAdminAction();
  const [key, setKey] = useState<string | null>(null);
  const d = detail.data;

  async function post(path: string, body: unknown, success: string) {
    const ok = await action.run(() => api.post(`/admin/v1/licenses/${id}/${path}`, body), success);
    if (ok) {
      detail.reload();
      onChanged();
    }
  }

  function withReason(path: string, success: string) {
    return (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      const body: Record<string, unknown> = { reason: data.get("reason") };
      if (path === "extend") body.days = Number(data.get("days"));
      void post(path, body, success);
    };
  }

  function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("customer_email") ?? "").trim();
    void post("assign", { customer_email: email }, "Lisans müşteriye atandı; artık uygulamada etkinleştirilebilir");
  }

  async function reveal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = new FormData(event.currentTarget).get("code");
    const result = await action.run(() => api.post<{ key: string }>(`/admin/v1/licenses/${id}/reveal`, { code }));
    if (result) setKey(result.key);
  }

  if (!d) return <Feedback error={detail.error} />;
  const unassigned = d.status === "generated" || d.status === "ready_for_sale";
  return (
    <Card className="space-y-4" as="section">
      <h2 className="text-lg font-semibold text-fg">
        Lisans #{d.serial} · <span data-testid="license-status">{licenseStatusLabel(d.status)}</span>
      </h2>
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-muted">Anahtar</dt>
        <dd className="font-mono" data-testid="license-key">{key ?? d.key_hint}</dd>
        <dt className="text-muted">Paket</dt>
        <dd>{d.plan_code}</dd>
        <dt className="text-muted">Müşteri</dt>
        <dd>{d.customer_email ?? "—"}</dd>
        <dt className="text-muted">Bitiş</dt>
        <dd>{dateTime(d.expires_at)}</dd>
        {d.frozen_reason ? (
          <>
            <dt className="text-muted">Dondurma nedeni</dt>
            <dd>{d.frozen_reason}</dd>
          </>
        ) : null}
      </dl>
      <Feedback error={action.error} message={action.message} />
      {unassigned ? (
        <p className="text-sm text-muted" data-testid="license-pool-note">
          Bu lisans satış havuzunda; bir müşteriye atanmadan uygulamada etkinleştirilemez.
        </p>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {unassigned && can(me, "license.generate") ? (
          <form onSubmit={assign} className="flex items-end gap-2">
            <label className="flex-1 text-sm text-fg">
              Atanacak müşterinin e-postası
              <input name="customer_email" type="email" required className={`mt-1 ${inputClass}`} />
            </label>
            <Button type="submit">Müşteriye ata</Button>
          </form>
        ) : null}
        {can(me, "license.freeze") && d.status !== "cancelled" ? (
          d.status === "frozen" ? (
            <Button variant="secondary" onClick={() => void post("unfreeze", {}, "Dondurma kaldırıldı")}>
              Dondurmayı kaldır
            </Button>
          ) : (
            <form onSubmit={withReason("freeze", "Lisans donduruldu")} className="flex items-end gap-2">
              <label className="flex-1 text-sm text-fg">
                Dondurma nedeni
                <input name="reason" required minLength={3} className={`mt-1 ${inputClass}`} />
              </label>
              <Button type="submit" variant="secondary">Dondur</Button>
            </form>
          )
        ) : null}
        {can(me, "license.extend") ? (
          <form onSubmit={withReason("extend", "Süre uzatıldı")} className="flex flex-wrap items-end gap-2">
            <label className="text-sm text-fg">
              Gün
              <input name="days" type="number" min={1} max={3650} required defaultValue={30} className={`mt-1 ${inputClass} w-24`} />
            </label>
            <label className="flex-1 text-sm text-fg">
              Uzatma nedeni
              <input name="reason" required minLength={3} className={`mt-1 ${inputClass}`} />
            </label>
            <Button type="submit" variant="secondary">Uzat</Button>
          </form>
        ) : null}
        {can(me, "license.cancel") && d.status !== "cancelled" ? (
          <form onSubmit={withReason("cancel", "Lisans iptal edildi")} className="flex items-end gap-2">
            <label className="flex-1 text-sm text-fg">
              İptal nedeni (geri alınamaz)
              <input name="reason" required minLength={3} className={`mt-1 ${inputClass}`} />
            </label>
            <Button type="submit" variant="secondary">İptal et</Button>
          </form>
        ) : null}
        {can(me, "license.reveal_key") && !key ? (
          <form onSubmit={(e) => void reveal(e)} className="flex items-end gap-2">
            <TotpInput id={`reveal-${id}`} />
            <Button type="submit" variant="secondary">Tam anahtarı göster</Button>
          </form>
        ) : null}
      </div>
      <details>
        <summary className="cursor-pointer text-sm font-medium text-fg">Geçmiş ({d.events.length})</summary>
        <ul className="mt-2 space-y-1 text-sm text-muted">
          {d.events.map((e) => (
            <li key={`${e.occurred_at}-${e.to_status}`}>
              {dateTime(e.occurred_at)} · {e.from_status ? `${licenseStatusLabel(e.from_status)} → ` : ""}
              {licenseStatusLabel(e.to_status)} ({e.actor_type})
            </li>
          ))}
        </ul>
      </details>
    </Card>
  );
}

export function Licenses() {
  const api = useApi();
  const { me } = useAdmin();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const list = useAdminQuery<{ items: LicenseRow[]; total: number }>(
    `/admin/v1/licenses?limit=50${query ? `&q=${encodeURIComponent(query)}` : ""}`,
  );
  const plans = useAdminQuery<PlanLite[]>(can(me, "plan.manage") ? "/admin/v1/plans" : null);
  const generate = useAdminAction();
  const [issued, setIssued] = useState<string | null>(null);

  async function onGenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email") ?? "").trim();
    const result = await generate.run(() =>
      api.post<{ id: string; key: string }>("/admin/v1/licenses", { plan_code: data.get("plan"), customer_email: email || null }),
    );
    if (result) {
      setIssued(result.key);
      list.reload();
    }
  }

  async function onBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const result = await generate.run(() =>
      api.post<{ batch_id: string; licenses: { id: string; key: string }[] }>("/admin/v1/licenses/batch", {
        plan_code: data.get("plan"),
        quantity: Number(data.get("quantity")),
        purpose: data.get("purpose"),
      }),
    );
    if (result) {
      download(`lisanslar-${result.batch_id}.csv`, toCsv(result.licenses.map((l) => ({ id: l.id, key: l.key }))));
      generate.setMessage(`${result.licenses.length} lisans üretildi; anahtarlar CSV olarak indirildi (bir kez).`);
      list.reload();
    }
  }

  const planOptions = plans.data ?? [{ code: "d30_1dev", name: "30 Gün - 1 Cihaz" }];
  return (
    <AdminPage title="Lisanslar" lead="Arama: tam anahtar, seri no, müşteri e-postası veya anahtarın son 4 karakteri.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(String(new FormData(e.currentTarget).get("q") ?? "").trim());
          setSelected(null);
        }}
        className="flex max-w-xl gap-2"
        role="search"
      >
        <label htmlFor="lisans-ara" className="visually-hidden">Lisans ara</label>
        <input id="lisans-ara" name="q" className={inputClass} placeholder="ATI-…, seri no veya e-posta" />
        <Button type="submit" variant="secondary">Ara</Button>
      </form>
      {can(me, "license.generate") || can(me, "license.bulk_generate") ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {can(me, "license.generate") ? (
            <Card as="section">
              <h2 className="font-semibold text-fg">Lisans üret</h2>
              <form onSubmit={(e) => void onGenerate(e)} className="mt-3 space-y-3">
                <label className="block text-sm text-fg">
                  Paket
                  <select name="plan" className={`mt-1 ${inputClass}`}>
                    {planOptions.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
                  </select>
                </label>
                <label className="block text-sm text-fg">
                  Müşteri e-postası (boşsa satış havuzuna)
                  <input name="email" type="email" className={`mt-1 ${inputClass}`} />
                </label>
                <p className="text-xs text-muted">
                  Havuzdaki lisans uygulamada etkinleşmez; önce Ayrıntı → Müşteriye ata gerekir.
                </p>
                <Button type="submit" disabled={generate.pending}>Üret</Button>
              </form>
              {issued ? (
                <div className="mt-3">
                  <p className="text-sm text-fg">Anahtar (yalnızca şimdi gösterilir):</p>
                  <code className="mt-1 block rounded bg-surface-2 px-3 py-2 font-mono text-fg" data-testid="issued-key">{issued}</code>
                </div>
              ) : null}
            </Card>
          ) : null}
          {can(me, "license.bulk_generate") ? (
            <Card as="section">
              <h2 className="font-semibold text-fg">Toplu üret</h2>
              <form onSubmit={(e) => void onBatch(e)} className="mt-3 space-y-3">
                <label className="block text-sm text-fg">
                  Paket
                  <select name="plan" className={`mt-1 ${inputClass}`}>
                    {planOptions.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
                  </select>
                </label>
                <label className="block text-sm text-fg">
                  Adet (en fazla 1000)
                  <input name="quantity" type="number" min={1} max={1000} defaultValue={10} className={`mt-1 ${inputClass} w-32`} />
                </label>
                <label className="block text-sm text-fg">
                  Amaç
                  <select name="purpose" className={`mt-1 ${inputClass}`}>
                    <option value="sale_pool">Satış havuzu</option>
                    <option value="promotion">Promosyon</option>
                    <option value="replacement">Değişim</option>
                    <option value="manual">Elle satış</option>
                  </select>
                </label>
                <Button type="submit" variant="secondary" disabled={generate.pending}>Üret ve CSV indir</Button>
              </form>
            </Card>
          ) : null}
        </div>
      ) : null}
      <Feedback error={generate.error ?? list.error} message={generate.message} />
      {list.data ? (
        <>
          <p className="text-sm text-muted" data-testid="license-total">{list.data.total} lisans</p>
          <Table caption="Lisanslar" head={["Seri", "Anahtar", "Paket", "Durum", "Müşteri", "Bilgisayar", "Bitiş", ""]}>
            {list.data.items.map((l) => (
              <tr key={l.id}>
                <td className={cell}>{l.serial}</td>
                <td className={`${cell} font-mono`}>{l.key_hint}</td>
                <td className={cell}>{l.plan_code}</td>
                <td className={cell}><StatusPill tone={licenseTone(l.status)}>{licenseStatusLabel(l.status)}</StatusPill></td>
                <td className={cell}>{l.customer_email ?? "—"}</td>
                <td className={cell}>{l.active_devices} / {l.device_limit}</td>
                <td className={cell}>{dateTime(l.expires_at)}</td>
                <td className={cell}>
                  <button type="button" className={smallButton} onClick={() => setSelected(l.id)} aria-label={`Lisans ${l.serial} ayrıntı`}>
                    Ayrıntı
                  </button>
                </td>
              </tr>
            ))}
          </Table>
        </>
      ) : null}
      {selected ? <Detail key={selected} id={selected} onChanged={list.reload} /> : null}
    </AdminPage>
  );
}
