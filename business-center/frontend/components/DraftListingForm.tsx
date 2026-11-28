"use client";
import Link from "next/link";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

export function DraftListingForm({ orgId, currency }: { orgId: string; currency: string | null }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ title: "", description: "", price: "", taxonomy_id: "", tags: "", quantity: "999" });
  const [res, setRes] = useState<{ ok: boolean; text: string } | null>(null);
  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v }));
  const tags = f.tags.split(",").map((x) => x.trim()).filter(Boolean);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const r = await clientApi(`/api/organizations/${orgId}/approvals/etsy-draft`, { method: "POST", body: JSON.stringify({
      title: f.title, description: f.description, price: Number(f.price), taxonomy_id: Number(f.taxonomy_id), tags,
      quantity: Number(f.quantity) }) });
    setRes(r.ok ? { ok: true, text: "Onaya sunuldu" } : { ok: false, text: r.error ?? "Hata" });
    if (r.ok) { setOpen(false); setF({ title: "", description: "", price: "", taxonomy_id: "", tags: "", quantity: "999" }); }
  }
  const input = "mt-1 w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm";
  if (!open) return (
    <span className="inline-flex items-center gap-2">
      <button type="button" onClick={() => { setOpen(true); setRes(null); }} className="rounded-xl border border-line bg-panel px-3 py-1.5 text-sm hover:bg-canvas">+ Taslak listeleme</button>
      {res?.ok && <Link href="/approvals" className="text-xs text-emerald-700 underline">{res.text}</Link>}
    </span>
  );
  return (
    <form onSubmit={submit} className="w-full space-y-3 rounded-2xl border border-line bg-panel p-4 text-sm">
      <h2 className="font-semibold">Yeni taslak listeleme</h2>
      <p className="text-xs text-muted">Onayladığınızda Etsy'de yalnızca TASLAK olarak oluşur. Fotoğraf ekleme ve yayına alma Etsy panelinden sizde kalır.</p>
      <label className="block">Başlık <span className="text-xs text-muted">({f.title.length}/140)</span>
        <input required maxLength={140} className={input} value={f.title} onChange={(e) => set("title", e.target.value)} /></label>
      <label className="block">Açıklama<textarea required rows={3} className={input} value={f.description} onChange={(e) => set("description", e.target.value)} /></label>
      <div className="grid gap-3 sm:grid-cols-3">
        <label>Fiyat ({currency ?? "mağaza para birimi"})<input required inputMode="decimal" pattern="\d+(\.\d{1,2})?" className={input} value={f.price} onChange={(e) => set("price", e.target.value)} /></label>
        <label>Adet<input required inputMode="numeric" pattern="\d{1,3}" className={input} value={f.quantity} onChange={(e) => set("quantity", e.target.value)} /></label>
        <label>Etsy kategori kimliği<input required inputMode="numeric" pattern="\d+" className={input} value={f.taxonomy_id} placeholder="ör. 1027" onChange={(e) => set("taxonomy_id", e.target.value)} /></label>
      </div>
      <label className="block">Etiketler (virgülle) <span className={`text-xs ${tags.length > 13 ? "text-yt" : "text-muted"}`}>({tags.length}/13)</span>
        <input className={input} value={f.tags} onChange={(e) => set("tags", e.target.value)} /></label>
      <div className="flex gap-2">
        <button className="rounded-lg bg-brand px-4 py-2 text-white">Onaya sun</button>
        <button type="button" onClick={() => setOpen(false)} className="rounded-lg border border-line px-4 py-2">Vazgeç</button>
      </div>
      {res && !res.ok && <p className="text-xs text-yt">{res.text}</p>}
    </form>
  );
}
