"use client";
import Link from "next/link";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

type Agent = { code: string; name: string; department: string };

export function StarterPack({ orgId, agents, tasks, ready, maxCost, maxParallel }:
  { orgId: string; agents: Agent[]; tasks: Record<string, string>; ready: { llm: boolean; profile: boolean };
    maxCost: number; maxParallel: number }) {
  const list = agents.filter((a) => tasks[a.code]);
  const [sel, setSel] = useState<Set<string>>(new Set(list.map((a) => a.code)));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const can = ready.llm && ready.profile;
  const toggle = (c: string) => setSel((s) => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n; });

  async function launch() {
    if (!confirm(`${sel.size} ajana ilk görevi verilecek. Görevler sırayla (aynı anda en fazla ${maxParallel}) çalışır. ` +
      `Her görevin üst sınırı $${maxCost.toFixed(2)}; toplam en fazla ~$${(sel.size * maxCost).toFixed(2)}. Devam edilsin mi?`)) return;
    setBusy(true); setMsg(null);
    const r = await clientApi(`/api/organizations/${orgId}/starter-tasks`, { method: "POST", body: JSON.stringify({ agent_codes: [...sel] }) });
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: `${r.data.queued} görev sıraya alındı. İlerlemeyi AI Ofis'ten izleyebilirsiniz.` } : { ok: false, text: r.error ?? "Hata" });
  }

  return (
    <section className="rounded-2xl border border-line bg-panel p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">İlk görev paketi</h2>
          <p className="text-sm text-muted">Her ajan kendi alanında, işletme profilinize göre ilk işini yapar. Görevler teker teker çalışır.</p>
        </div>
        <button disabled={!can || busy || !sel.size} onClick={launch}
          className="rounded-xl bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Sıraya alınıyor…" : `${sel.size} görevi başlat`}
        </button>
      </div>
      {!can && (
        <ul className="mt-3 space-y-1 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
          {!ready.llm && <li>⚠ Claude API anahtarı tanımlı değil (sunucuda BC_ANTHROPIC_API_KEY).</li>}
          {!ready.profile && <li>⚠ <Link href="/settings" className="underline">Settings › İşletme Profili</Link>'nde YouTube veya Etsy nişini doldurun.</li>}
        </ul>
      )}
      {msg && <p role="status" className={`mt-3 text-sm ${msg.ok ? "text-emerald-700" : "text-yt"}`}>{msg.text}</p>}
      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {list.map((a) => (
          <li key={a.code}>
            <label className="flex cursor-pointer gap-3 rounded-xl border border-line p-3 hover:bg-canvas">
              <input type="checkbox" className="mt-1" checked={sel.has(a.code)} onChange={() => toggle(a.code)} />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{a.name}</span>
                <span className="block text-xs text-muted">{tasks[a.code]}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  );
}
