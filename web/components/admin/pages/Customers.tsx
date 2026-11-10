"use client";

import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, StatusPill, Table, TotpInput, cell, inputClass, smallButton, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { Button, Card } from "@/components/ui";
import { can, dateTime } from "@/lib/admin";
import { licenseStatusLabel } from "@/lib/format";

interface CustomerRow {
  id: string;
  email: string;
  full_name: string | null;
  status: string;
  created_at: string;
  licenses: number;
  email_verified: boolean;
}

interface CustomerDetail extends CustomerRow {
  blocked_reason: string | null;
  licenses_list?: never;
  devices: { id: string; display_name: string; platform: string; last_seen_at: string; revoked_at: string | null }[];
}

/** Müşteriyi silme (yalnızca süper yönetici): e-posta yazılarak ve doğrulama koduyla onaylanır. */
function DeleteCustomer({ id, email, onDeleted }: { id: string; email: string; onDeleted: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const [typed, setTyped] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const ok = await action.run(
      () =>
        api.post<{ licenses_cancelled: number }>(`/admin/v1/customers/${id}/delete`, {
          confirm_email: typed,
          reason: data.get("reason"),
          code: data.get("code"),
        }),
      "Müşteri silindi",
    );
    if (ok) onDeleted();
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 rounded-2xl border border-danger-border bg-danger-bg/40 p-4" aria-labelledby="musteri-sil">
      <h3 id="musteri-sil" className="font-semibold text-danger-fg">
        Müşteriyi sil
      </h3>
      <p className="text-sm text-fg">
        Kişisel veriler (e-posta, ad, parola) kalıcı olarak silinir, lisansları iptal edilir ve cihazları kapatılır; uygulama bir
        sonraki lisans yenilemesinde durur. Siparişler yasal saklama süresi boyunca kişisel veri olmadan korunur. Bu işlem geri
        alınamaz.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <label htmlFor="sil-eposta" className="block text-sm font-medium text-fg">
          Onaylamak için e-postayı yazın: <span className="font-mono">{email}</span>
          <input id="sil-eposta" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" required className={`mt-1 ${inputClass}`} />
        </label>
        <label htmlFor="sil-neden" className="block text-sm font-medium text-fg">
          Silme nedeni
          <input id="sil-neden" name="reason" required minLength={3} maxLength={300} placeholder="Ör. KVKK silme talebi" className={`mt-1 ${inputClass}`} />
        </label>
      </div>
      <TotpInput id="sil-kod" />
      <Button type="submit" variant="danger" disabled={action.pending || typed.trim().toLowerCase() !== email.toLowerCase()}>
        Müşteriyi kalıcı olarak sil
      </Button>
      <Feedback error={action.error} message={action.message} />
    </form>
  );
}

function Detail({ id, onChanged, onDeleted }: { id: string; onChanged: () => void; onDeleted: () => void }) {
  const api = useApi();
  const { me } = useAdmin();
  const detail = useAdminQuery<CustomerDetail & { licenses: { id: string; serial: number; key_hint: string; plan_code: string; status: string }[] }>(
    `/admin/v1/customers/${id}`,
  );
  const action = useAdminAction();
  const d = detail.data;

  async function run(path: string, body: unknown, success: string) {
    const ok = await action.run(() => api.post(path, body), success);
    if (ok) {
      detail.reload();
      onChanged();
    }
  }

  if (!d) return <Feedback error={detail.error} />;
  return (
    <Card as="section" className="space-y-4">
      <h2 className="text-lg font-semibold text-fg">
        {d.email}{" "}
        <StatusPill testId="customer-status" tone={d.status === "blocked" ? "danger" : "success"}>
          {d.status === "blocked" ? "Engelli" : "Etkin"}
        </StatusPill>
      </h2>
      {d.blocked_reason ? <p className="text-sm text-muted">Engel nedeni: {d.blocked_reason}</p> : null}
      <Feedback error={action.error} message={action.message} />
      {can(me, "customer.block") ? (
        d.status === "blocked" ? (
          <Button variant="secondary" onClick={() => void run(`/admin/v1/customers/${id}/unblock`, {}, "Engel kaldırıldı")}>
            Engeli kaldır
          </Button>
        ) : (
          <form
            onSubmit={(e: FormEvent<HTMLFormElement>) => {
              e.preventDefault();
              void run(`/admin/v1/customers/${id}/block`, { reason: new FormData(e.currentTarget).get("reason") }, "Müşteri engellendi; oturumları kapatıldı");
            }}
            className="flex max-w-xl items-end gap-2"
          >
            <label className="flex-1 text-sm text-fg">
              Engelleme nedeni
              <input name="reason" required minLength={3} className={`mt-1 ${inputClass}`} />
            </label>
            <Button type="submit" variant="secondary">Engelle</Button>
          </form>
        )
      ) : null}
      <div>
        <h3 className="text-sm font-semibold text-fg">Lisanslar</h3>
        <ul className="mt-1 text-sm text-fg">
          {d.licenses.length === 0 ? <li className="text-muted">Yok</li> : null}
          {d.licenses.map((l) => (
            <li key={l.id}>#{l.serial} · {l.plan_code} · {licenseStatusLabel(l.status)} · <span className="font-mono">{l.key_hint}</span></li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-fg">Cihazlar</h3>
        <ul className="mt-1 space-y-2 text-sm text-fg">
          {d.devices.length === 0 ? <li className="text-muted">Yok</li> : null}
          {d.devices.map((device) => (
            <li key={device.id} className="flex flex-wrap items-center gap-3">
              <span>{device.display_name} ({device.platform}) · son görülme {dateTime(device.last_seen_at)}</span>
              {device.revoked_at ? (
                <span className="text-muted">Kaldırıldı</span>
              ) : can(me, "device.revoke") ? (
                <button
                  type="button"
                  className={smallButton}
                  onClick={() => void run(`/admin/v1/devices/${device.id}/revoke`, { reason: "yönetici kaldırdı" }, "Cihaz kaldırıldı")}
                >
                  Cihazı kaldır
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
      {can(me, "customer.delete") ? (
        <DeleteCustomer
          id={id}
          email={d.email}
          onDeleted={() => {
            onChanged();
            onDeleted();
          }}
        />
      ) : null}
    </Card>
  );
}

export function Customers() {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [deletedNote, setDeletedNote] = useState<string | null>(null);
  const list = useAdminQuery<{ items: CustomerRow[]; total: number }>(
    `/admin/v1/customers?limit=50${query ? `&q=${encodeURIComponent(query)}` : ""}`,
  );
  return (
    <AdminPage title="Müşteriler" lead="Hesaplar, lisanslar ve cihazlar. Silme yalnızca süper yöneticiye açıktır ve doğrulama kodu ister.">
      <form
        role="search"
        className="flex max-w-xl gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(String(new FormData(e.currentTarget).get("q") ?? "").trim());
          setSelected(null);
        }}
      >
        <label htmlFor="musteri-ara" className="visually-hidden">Müşteri ara</label>
        <input id="musteri-ara" name="q" className={inputClass} placeholder="E-posta veya ad" />
        <Button type="submit" variant="secondary">Ara</Button>
      </form>
      <Feedback error={list.error} />
      {list.data ? (
        <Table caption="Müşteriler" head={["E-posta", "Ad", "Durum", "Lisans", "Kayıt", ""]}>
          {list.data.items.map((c) => (
            <tr key={c.id}>
              <td className={cell}>{c.email}</td>
              <td className={cell}>{c.full_name ?? "—"}</td>
              <td className={cell}>
                <StatusPill tone={c.status === "blocked" ? "danger" : c.email_verified ? "success" : "warn"}>
                  {c.status === "blocked" ? "Engelli" : c.email_verified ? "Etkin" : "Doğrulanmamış"}
                </StatusPill>
              </td>
              <td className={cell}>{c.licenses}</td>
              <td className={cell}>{dateTime(c.created_at)}</td>
              <td className={cell}>
                <button type="button" className={smallButton} onClick={() => setSelected(c.id)} aria-label={`${c.email} ayrıntı`}>
                  Ayrıntı
                </button>
              </td>
            </tr>
          ))}
        </Table>
      ) : null}
      {deletedNote ? (
        <p role="status" className="text-sm text-success-fg" data-testid="customer-deleted">
          {deletedNote}
        </p>
      ) : null}
      {selected ? (
        <Detail
          key={selected}
          id={selected}
          onChanged={list.reload}
          onDeleted={() => {
            setSelected(null);
            setDeletedNote("Müşteri silindi; lisansları iptal edildi.");
          }}
        />
      ) : null}
    </AdminPage>
  );
}
