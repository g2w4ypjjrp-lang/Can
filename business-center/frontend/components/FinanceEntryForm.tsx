"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

const KINDS = [["revenue", "Gelir"], ["expense", "Gider"], ["fee", "Platform ücreti"], ["refund", "İade"],
  ["discount", "İndirim"], ["tax", "Vergi (ayrı raporlanır)"]] as const;
const CATS: Record<string, string[]> = {
  revenue: ["sales", "ad_revenue", "other"],
  expense: ["printify_production", "shipping", "etsy_ads", "youtube_ads", "voiceover", "software", "ai", "other"],
  fee: ["etsy_fees"], refund: ["refund"], discount: ["discount"], tax: ["tax"],
};

export function FinanceEntryForm({ orgId }: { orgId: string }) {
  const router = useRouter();
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ kind: "expense", department: "etsy", category: "printify_production", amount: "",
    currency: "USD", occurred_on: today });
  const [msg, setMsg] = useState<string | null>(null);
  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v, ...(k === "kind" ? { category: CATS[v][0] } : {}) }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const r = await clientApi(`/api/organizations/${orgId}/finance/entries`, { method: "POST", body: JSON.stringify(f) });
    setMsg(r.ok ? "Kaydedildi." : r.error ?? "Hata");
    if (r.ok) { setF({ ...f, amount: "" }); router.refresh(); }
  }
  const cls = "rounded-lg border border-line bg-transparent px-3 py-2 text-sm";
  return (
    <form onSubmit={submit} className="space-y-3 rounded-2xl border border-line bg-panel p-4">
      <h2 className="font-semibold">Manuel kayıt</h2>
      <p className="text-xs text-muted">Entegrasyonlar bağlanana kadar gelir ve giderleri buradan girebilirsiniz.</p>
      <div className="grid gap-2 sm:grid-cols-3">
        <select className={cls} value={f.kind} onChange={(e) => set("kind", e.target.value)}>
          {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <select className={cls} value={f.department} onChange={(e) => set("department", e.target.value)}>
          <option value="etsy">Etsy</option><option value="youtube">YouTube</option>
          {f.kind !== "revenue" && <option value="shared">Ortak</option>}</select>
        <select className={cls} value={f.category} onChange={(e) => set("category", e.target.value)}>
          {CATS[f.kind].map((c) => <option key={c}>{c}</option>)}</select>
        <input className={cls} required inputMode="decimal" pattern="\d+(\.\d{1,2})?" placeholder="Tutar (ör. 12.50)"
          value={f.amount} onChange={(e) => set("amount", e.target.value)} />
        <input className={cls} required pattern="[A-Z]{3}" maxLength={3} value={f.currency}
          onChange={(e) => set("currency", e.target.value.toUpperCase())} />
        <input className={cls} type="date" required value={f.occurred_on} onChange={(e) => set("occurred_on", e.target.value)} />
      </div>
      <div className="flex items-center gap-3">
        <button className="rounded-lg bg-brand px-4 py-2 text-sm text-white">Kaydet</button>
        {msg && <span role="status" className="text-sm text-muted">{msg}</span>}
      </div>
    </form>
  );
}
