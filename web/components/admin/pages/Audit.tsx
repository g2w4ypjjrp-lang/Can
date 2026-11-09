"use client";

import { useState } from "react";

import { useApi } from "@/components/ApiContext";
import { AdminPage, Feedback, Table, cell, inputClass, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { Button } from "@/components/ui";
import { dateTime } from "@/lib/admin";

interface Entry {
  id: number;
  occurred_at: string;
  actor_type: string;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  ip: string | null;
  details: Record<string, unknown>;
}

export function Audit() {
  const api = useApi();
  const [action, setAction] = useState("");
  const log = useAdminQuery<Entry[]>(`/admin/v1/audit?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}`);
  const verify = useAdminAction();
  return (
    <AdminPage
      title="Denetim kaydı"
      lead="Kayıtlar yalnızca eklenebilir ve her kayıt öncekinin özetini içerir (hash zinciri); silme veya değiştirme tespit edilir."
      actions={
        <Button
          variant="secondary"
          onClick={() =>
            void verify.run(async () => {
              const r = await api.get<{ intact: boolean; first_broken_id: number | null; entries: number }>("/admin/v1/audit/verify");
              if (!r.intact) throw new Error(`Zincir bozuk: kayıt #${r.first_broken_id}`);
              verify.setMessage(`Zincir sağlam (${r.entries} kayıt doğrulandı).`);
            })
          }
        >
          Zinciri doğrula
        </Button>
      }
    >
      <Feedback error={verify.error ?? log.error} message={verify.message} />
      <label className="block max-w-xs text-sm text-fg">
        Eylem (önek)
        <input value={action} onChange={(e) => setAction(e.target.value.replace(/[^a-z_.]/g, ""))} placeholder="ör. admin.license" className={`mt-1 ${inputClass}`} />
      </label>
      {log.data ? (
        <Table caption="Denetim kaydı" head={["#", "Zaman", "Aktör", "Eylem", "Hedef", "IP"]}>
          {log.data.map((e) => (
            <tr key={e.id}>
              <td className={cell}>{e.id}</td>
              <td className={cell}>{dateTime(e.occurred_at)}</td>
              <td className={cell}>{e.actor_type}{e.actor_id ? ` · ${e.actor_id.slice(0, 8)}` : ""}</td>
              <td className={`${cell} font-mono text-xs`}>{e.action}</td>
              <td className={cell}>{e.target_type ? `${e.target_type} ${String(e.target_id ?? "").slice(0, 8)}` : "—"}</td>
              <td className={cell}>{e.ip ?? "—"}</td>
            </tr>
          ))}
        </Table>
      ) : null}
    </AdminPage>
  );
}
