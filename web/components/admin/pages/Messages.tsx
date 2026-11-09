"use client";

import { useState } from "react";

import { useApi } from "@/components/ApiContext";
import { useAdmin } from "@/components/admin/AdminSession";
import { AdminPage, Feedback, inputClass, useAdminAction, useAdminQuery } from "@/components/admin/kit";
import { Card } from "@/components/ui";
import { can, dateTime } from "@/lib/admin";

interface Message {
  id: number;
  name: string;
  email: string;
  topic: string;
  message: string;
  status: string;
  created_at: string;
}

const STATUS: Record<string, string> = { new: "Yeni", in_progress: "İşlemde", closed: "Kapandı", spam: "İstenmeyen" };
const TOPIC: Record<string, string> = { support: "Teknik destek", license: "Lisans", sales: "Satış", privacy: "KVKK", other: "Diğer" };

export function Messages() {
  const api = useApi();
  const { me } = useAdmin();
  const [filter, setFilter] = useState("new");
  const list = useAdminQuery<Message[]>(`/admin/v1/messages?limit=100${filter ? `&status=${filter}` : ""}`);
  const action = useAdminAction();
  return (
    <AdminPage title="İletişim mesajları" lead="Yanıtlar e-postayla gönderilir; e-posta sağlayıcısı yayına alınınca (G5) panelden de yanıtlanabilecek.">
      <label className="block max-w-xs text-sm text-fg">
        Durum
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className={`mt-1 ${inputClass}`}>
          <option value="">Tümü</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <Feedback error={list.error ?? action.error} message={action.message} />
      <ul className="space-y-3">
        {list.data?.length === 0 ? <li className="text-sm text-muted">Mesaj yok.</li> : null}
        {list.data?.map((m) => (
          <li key={m.id}>
            <Card as="article" className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold text-fg">{m.name} · <a className="text-link underline" href={`mailto:${m.email}`}>{m.email}</a></h2>
                <span className="text-xs text-muted">{TOPIC[m.topic] ?? m.topic} · {dateTime(m.created_at)}</span>
              </div>
              <p className="whitespace-pre-wrap text-sm text-fg">{m.message}</p>
              {can(me, "customer.update") ? (
                <label className="flex items-center gap-2 text-sm text-fg">
                  Durum
                  <select
                    value={m.status}
                    aria-label={`${m.name} mesajının durumu`}
                    onChange={(e) => {
                      const status = e.target.value;
                      void action.run(() => api.post(`/admin/v1/messages/${m.id}/status`, { status }), "Durum güncellendi").then(list.reload);
                    }}
                    className={`${inputClass} w-40`}
                  >
                    {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
              ) : null}
            </Card>
          </li>
        ))}
      </ul>
    </AdminPage>
  );
}
