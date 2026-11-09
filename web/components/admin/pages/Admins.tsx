"use client";

import { useState, type FormEvent } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, Table, cell, inputClass, smallButton, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { Button, Card } from "@/components/ui";
import { ROLE_LABELS, dateTime } from "@/lib/admin";

interface AdminRow {
  id: string;
  email: string;
  full_name: string;
  status: string;
  last_login_at: string | null;
  two_factor: boolean;
  roles: string[];
}

const STATUS: Record<string, string> = { invited: "Davetli", active: "Etkin", blocked: "Engelli" };

export function Admins() {
  const api = useApi();
  const { me } = useAdmin();
  const list = useAdminQuery<AdminRow[]>("/admin/v1/admins");
  const action = useAdminAction();
  const [link, setLink] = useState<string | null>(null);

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const result = await action.run(() =>
      api.post<{ invite_url: string }>("/admin/v1/admins", {
        email: data.get("email"),
        full_name: data.get("full_name"),
        roles: data.getAll("roles"),
      }),
    );
    if (result) {
      setLink(result.invite_url);
      list.reload();
    }
  }

  async function act(path: string, success: string) {
    const result = await action.run(() => api.post<{ invite_url?: string }>(path), success);
    if (result?.invite_url) setLink(result.invite_url);
    list.reload();
  }

  return (
    <AdminPage title="Yöneticiler" lead="Her yönetici iki aşamalı doğrulama (TOTP) ile giriş yapar. Davet bağlantısı 72 saat geçerlidir ve yalnızca bir kez gösterilir.">
      <Card as="section">
        <h2 className="font-semibold text-fg">Yönetici davet et</h2>
        <form onSubmit={(e) => void invite(e)} className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-fg">
            E-posta
            <input name="email" type="email" required className={`mt-1 ${inputClass}`} />
          </label>
          <label className="text-sm text-fg">
            Ad soyad
            <input name="full_name" required minLength={2} className={`mt-1 ${inputClass}`} />
          </label>
          <fieldset className="sm:col-span-2">
            <legend className="text-sm text-fg">Roller</legend>
            <div className="mt-1 flex flex-wrap gap-4">
              {Object.entries(ROLE_LABELS).map(([code, label]) => (
                <label key={code} className="flex items-center gap-2 text-sm text-fg">
                  <input type="checkbox" name="roles" value={code} defaultChecked={code === "support"} className="h-4 w-4" />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <Button type="submit" disabled={action.pending}>Davet oluştur</Button>
          </div>
        </form>
        {link ? (
          <div className="mt-4">
            <p className="text-sm text-fg">Davet bağlantısı (yalnızca şimdi gösterilir; güvenli bir kanalla iletin):</p>
            <code className="mt-1 block break-all rounded bg-surface-2 px-3 py-2 font-mono text-xs text-fg" data-testid="invite-link">{link}</code>
          </div>
        ) : null}
      </Card>
      <Feedback error={action.error ?? list.error} message={action.message} />
      {list.data ? (
        <Table caption="Yöneticiler" head={["E-posta", "Ad", "Roller", "Durum", "2FA", "Son giriş", ""]}>
          {list.data.map((a) => (
            <tr key={a.id}>
              <td className={cell}>{a.email}</td>
              <td className={cell}>{a.full_name}</td>
              <td className={cell}>{a.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}</td>
              <td className={cell}>{STATUS[a.status] ?? a.status}</td>
              <td className={cell}>{a.two_factor ? "Açık" : "—"}</td>
              <td className={cell}>{dateTime(a.last_login_at)}</td>
              <td className={cell}>
                {a.id === me?.id ? (
                  <span className="text-xs text-muted">Siz</span>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {a.status === "blocked" ? (
                      <button type="button" className={smallButton} onClick={() => void act(`/admin/v1/admins/${a.id}/unblock`, "Engel kaldırıldı")}>Engeli kaldır</button>
                    ) : (
                      <button type="button" className={smallButton} onClick={() => void act(`/admin/v1/admins/${a.id}/block`, "Yönetici engellendi")}>Engelle</button>
                    )}
                    <button type="button" className={smallButton} onClick={() => void act(`/admin/v1/admins/${a.id}/reset-2fa`, "2FA sıfırlandı; yeni davet bağlantısı oluşturuldu")}>2FA sıfırla</button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </Table>
      ) : null}
    </AdminPage>
  );
}
