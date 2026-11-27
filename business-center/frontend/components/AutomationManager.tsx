"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

type Rule = { id: string; name: string; schedule_cron: string; timezone: string; command: string; enabled: boolean;
  last_run_at: string | null; next_run_at: string | null };
type Template = { key: string; name: string; cron: string; command: string };

export function AutomationManager({ orgId, rules, templates, canEdit }:
  { orgId: string; rules: Rule[]; templates: Template[]; canEdit: boolean }) {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", schedule_cron: "0 9 * * 1", command: "" });
  const used = new Set(rules.map((r) => r.name));

  async function call(path: string, init: RequestInit) {
    setErr(null);
    const r = await clientApi(path, init);
    if (!r.ok) setErr(r.error ?? "Hata"); else router.refresh();
  }
  const create = (b: object) => call(`/api/organizations/${orgId}/automation`, { method: "POST", body: JSON.stringify(b) });

  return (
    <div className="space-y-6">
      {err && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{err}</p>}
      <section className="rounded-2xl border border-line bg-panel">
        <h2 className="border-b border-line p-4 font-semibold">Kurallar</h2>
        {!rules.length && <p className="p-4 text-sm text-muted">Henüz kural yok. Aşağıdaki şablonlardan ekleyebilirsiniz.</p>}
        <ul className="divide-y divide-line">
          {rules.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{r.name}</p>
                <p className="truncate text-xs text-muted"><code>{r.schedule_cron}</code> · {r.timezone} · {r.command}</p>
                <p className="text-xs text-muted">
                  {r.next_run_at ? `Sonraki: ${new Date(r.next_run_at).toLocaleString("tr-TR")}` : "Kapalı"}
                  {r.last_run_at && ` · Son: ${new Date(r.last_run_at).toLocaleString("tr-TR")}`}
                </p>
              </div>
              {canEdit && <>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={r.enabled}
                    onChange={(e) => call(`/api/automation/${r.id}`, { method: "PATCH", body: JSON.stringify({ enabled: e.target.checked }) })} />
                  Etkin
                </label>
                <button onClick={() => confirm("Kural silinsin mi?") && call(`/api/automation/${r.id}`, { method: "DELETE" })}
                  className="text-sm text-muted underline">Sil</button>
              </>}
            </li>
          ))}
        </ul>
      </section>

      {canEdit && <>
        <section>
          <h2 className="mb-3 font-semibold">Hazır şablonlar</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {templates.map((t) => (
              <div key={t.key} className="rounded-xl border border-line bg-panel p-4">
                <p className="font-medium">{t.name}</p>
                <p className="mt-1 text-xs text-muted"><code>{t.cron}</code> · {t.command}</p>
                <button disabled={used.has(t.name)} onClick={() => create({ name: t.name, schedule_cron: t.cron, command: t.command })}
                  className="mt-3 rounded-lg border border-line px-3 py-1 text-sm disabled:opacity-50">
                  {used.has(t.name) ? "Eklendi" : "Ekle (kapalı)"}
                </button>
              </div>
            ))}
          </div>
        </section>

        <form className="space-y-3 rounded-2xl border border-line bg-panel p-4"
          onSubmit={(e) => { e.preventDefault(); create(form); }}>
          <h2 className="font-semibold">Özel kural</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <input required placeholder="Ad" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="rounded-lg border border-line bg-transparent px-3 py-2" />
            <input required placeholder="Cron (dk sa gün ay hafta)" value={form.schedule_cron}
              onChange={(e) => setForm({ ...form, schedule_cron: e.target.value })}
              className="rounded-lg border border-line bg-transparent px-3 py-2 font-mono" />
          </div>
          <textarea required minLength={3} placeholder="CEO'ya verilecek komut" value={form.command} rows={2}
            onChange={(e) => setForm({ ...form, command: e.target.value })}
            className="w-full rounded-lg border border-line bg-transparent px-3 py-2" />
          <button className="rounded-lg bg-brand px-4 py-2 text-sm text-white">Ekle (kapalı olarak)</button>
        </form>
      </>}
    </div>
  );
}
