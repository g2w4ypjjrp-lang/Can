"use client";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

type Field = { key: string; label: string; hint?: string; long?: boolean; placeholder?: string };
const GROUPS: { title: string; fields: Field[] }[] = [
  { title: "Marka", fields: [
    { key: "brand_name", label: "Marka adı" },
    { key: "language", label: "İçerik dili", placeholder: "Türkçe / English" },
    { key: "tone", label: "Marka dili / ton", placeholder: "Sıcak, sade, esprili…" },
    { key: "goals", label: "Hedefler", long: true, placeholder: "ör. 6 ayda 10 bin abone, ayda 100 Etsy satışı" },
  ] },
  { title: "YouTube", fields: [
    { key: "youtube_channel_url", label: "Kanal adresi", placeholder: "https://www.youtube.com/@…" },
    { key: "youtube_niche", label: "Kanalın konusu (niş)", long: true, placeholder: "ör. Minimalist ev dekorasyonu ve DIY" },
    { key: "youtube_audience", label: "Hedef kitle", long: true, placeholder: "ör. 25-40 yaş, ilk evini döşeyenler" },
  ] },
  { title: "Etsy + Printify", fields: [
    { key: "etsy_shop_name", label: "Mağaza adı" },
    { key: "etsy_shop_url", label: "Mağaza adresi", placeholder: "https://www.etsy.com/shop/…" },
    { key: "etsy_niche", label: "Mağazanın konusu (niş)", long: true, placeholder: "ör. Minimalist duvar posterleri" },
    { key: "etsy_products", label: "Ürün tipleri", placeholder: "poster, tişört, kupa…" },
    { key: "price_range", label: "Fiyat aralığı", placeholder: "15-35" },
    { key: "currency", label: "Para birimi", placeholder: "USD" },
    { key: "target_markets", label: "Hedef pazarlar", placeholder: "ABD, Birleşik Krallık, Almanya" },
  ] },
  { title: "Sınırlar", fields: [
    { key: "avoid", label: "Kaçınılacak konular / kurallar", long: true, placeholder: "ör. siyaset, ünlü isimleri, rakip markalar" },
  ] },
];

export function ProfileForm({ orgId, initial, canEdit }: { orgId: string; initial: Record<string, string> | null; canEdit: boolean }) {
  const [v, setV] = useState<Record<string, string>>(initial ?? { language: "Türkçe", currency: "USD" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null);
    const r = await clientApi(`/api/organizations/${orgId}/profile`, { method: "PUT", body: JSON.stringify(v) });
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: "Kaydedildi. Ajanlar bundan sonraki her görevde bu profili kullanacak." } : { ok: false, text: r.error ?? "Hata" });
  }
  const input = "mt-1 w-full rounded-xl border border-line bg-transparent px-3 py-2 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

  return (
    <form onSubmit={save} className="space-y-6">
      {GROUPS.map((g) => (
        <fieldset key={g.title} disabled={!canEdit} className="rounded-2xl border border-line bg-panel p-5">
          <legend className="px-1 text-sm font-semibold">{g.title}</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            {g.fields.map((f) => (
              <label key={f.key} className={`block text-sm ${f.long ? "sm:col-span-2" : ""}`}>
                <span className="text-muted">{f.label}</span>
                {f.long
                  ? <textarea rows={2} className={input} value={v[f.key] ?? ""} placeholder={f.placeholder}
                      onChange={(e) => setV({ ...v, [f.key]: e.target.value })} />
                  : <input className={input} value={v[f.key] ?? ""} placeholder={f.placeholder}
                      maxLength={f.key === "currency" ? 3 : 300}
                      onChange={(e) => setV({ ...v, [f.key]: f.key === "currency" ? e.target.value.toUpperCase() : e.target.value })} />}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      {canEdit && (
        <div className="flex items-center gap-3">
          <button disabled={busy} className="rounded-xl bg-brand px-5 py-2.5 text-sm font-medium text-white disabled:opacity-60">
            {busy ? "Kaydediliyor…" : "Profili kaydet"}
          </button>
          {msg && <span role="status" className={`text-sm ${msg.ok ? "text-emerald-700" : "text-yt"}`}>{msg.text}</span>}
        </div>
      )}
    </form>
  );
}
