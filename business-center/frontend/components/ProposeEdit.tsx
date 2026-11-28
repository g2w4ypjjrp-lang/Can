"use client";
import Link from "next/link";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

/** Bir listeleme/video için değişiklik önerir; değişiklik Approval Center'da onayınızı bekler. */
export function ProposeEdit({ orgId, action, targetId, title, tags, maxTitle, maxTags }:
  { orgId: string; action: "etsy.listing.update" | "youtube.video.update_metadata"; targetId: string; title: string;
    tags: string[]; maxTitle: number; maxTags?: number }) {
  const [open, setOpen] = useState(false);
  const [t, setT] = useState(title);
  const [tg, setTg] = useState(tags.join(", "));
  const [reason, setReason] = useState("");
  const [res, setRes] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const newTags = tg.split(",").map((x) => x.trim()).filter(Boolean);
    const changes: Record<string, unknown> = {};
    if (t.trim() !== title) changes.title = t.trim();
    if (newTags.join(",") !== tags.join(",")) changes.tags = newTags;
    if (!Object.keys(changes).length) return setRes({ ok: false, text: "Değişiklik yok" });
    const r = await clientApi(`/api/organizations/${orgId}/approvals`, { method: "POST", body: JSON.stringify({
      action, target_id: targetId, changes, reason: reason || "Başlık/etiket iyileştirmesi", expected_outcome: "Daha iyi arama görünürlüğü" }) });
    setRes(r.ok ? { ok: true, text: "Onaya sunuldu" } : { ok: false, text: r.error ?? "Hata" });
    if (r.ok) setOpen(false);
  }

  if (!open) return (
    <span className="inline-flex items-center gap-2">
      <button type="button" onClick={() => { setOpen(true); setRes(null); }} className="text-xs text-brand underline">Düzenleme öner</button>
      {res && (res.ok ? <Link href="/approvals" className="text-xs text-emerald-700 underline">{res.text}</Link>
        : <span className="text-xs text-yt">{res.text}</span>)}
    </span>
  );
  const input = "mt-1 w-full rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm";
  const tagCount = tg.split(",").filter((x) => x.trim()).length;
  return (
    <form onSubmit={submit} className="mt-2 w-full space-y-2 rounded-xl border border-line bg-canvas p-3 text-sm">
      <label className="block">Başlık <span className="text-xs text-muted">({t.length}/{maxTitle})</span>
        <input className={input} value={t} maxLength={maxTitle} onChange={(e) => setT(e.target.value)} /></label>
      <label className="block">Etiketler (virgülle) {maxTags && <span className={`text-xs ${tagCount > maxTags ? "text-yt" : "text-muted"}`}>({tagCount}/{maxTags})</span>}
        <input className={input} value={tg} onChange={(e) => setTg(e.target.value)} /></label>
      <label className="block">Neden
        <input className={input} value={reason} maxLength={2000} placeholder="ör. Rakiplerin kullandığı anahtar kelimeler" onChange={(e) => setReason(e.target.value)} /></label>
      <div className="flex gap-2">
        <button className="rounded-lg bg-brand px-3 py-1.5 text-white">Onaya sun</button>
        <button type="button" onClick={() => setOpen(false)} className="rounded-lg border border-line px-3 py-1.5">Vazgeç</button>
      </div>
      {res && !res.ok && <p className="text-xs text-yt">{res.text}</p>}
      <p className="text-xs text-muted">Hiçbir şey hemen değişmez. Approval Center'da onayladığınızda, yazma izni varsa uygulanır.</p>
    </form>
  );
}
