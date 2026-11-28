"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

type State = { status: string; display_name?: string | null; last_error?: string | null; last_synced_at?: string | null };

export function EtsyCard({ orgId, state, canEdit }: { orgId: string; state: State; canEdit: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const base = `/api/organizations/${orgId}/integrations/etsy`;
  const connected = state.status === "connected" || state.status === "error";

  async function start() {
    setBusy(true); setMsg(null);
    const r = await clientApi(base + "/start", { method: "POST" });
    if (!r.ok) { setBusy(false); return setMsg({ ok: false, text: r.error ?? "Başlatılamadı" }); }
    window.location.assign(r.data.url);   // Etsy izin sayfası
  }
  async function act(path: string, method: string, ok: (d: any) => string) {
    setBusy(true); setMsg(null);
    const r = await clientApi(base + path, { method });
    setBusy(false); setMsg(r.ok ? { ok: true, text: ok(r.data) } : { ok: false, text: r.error ?? "Hata" }); router.refresh();
  }

  return (
    <div className="space-y-3 text-sm">
      {connected ? (
        <>
          <p>Mağaza: <b>{state.display_name}</b></p>
          <p className="text-xs text-muted">Son senkron: {state.last_synced_at ? new Date(state.last_synced_at).toLocaleString("tr-TR") : "henüz yok"}</p>
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={() => act("/sync", "POST", (d) => `${d.listings} listeleme, ${d.orders} sipariş senkronlandı`)}
                className="rounded-xl bg-brand px-4 py-2 text-white disabled:opacity-60">{busy ? "Çalışıyor…" : "Senkronla"}</button>
              <button disabled={busy} onClick={() => confirm("Etsy bağlantısı kesilsin ve tokenlar silinsin mi?") && act("", "DELETE", () => "Bağlantı kesildi")}
                className="rounded-xl border border-line px-4 py-2">Bağlantıyı kes</button>
            </div>
          )}
        </>
      ) : canEdit ? (
        <>
          <p className="text-muted">Etsy hesabınızla güvenli giriş yapıp yalnızca okuma izni verirsiniz (mağaza, listelemeler, siparişler).</p>
          <button disabled={busy} onClick={start} className="rounded-xl bg-brand px-4 py-2 text-white disabled:opacity-60">
            {busy ? "Yönlendiriliyor…" : "Etsy'yi bağla"}</button>
        </>
      ) : <p className="text-muted">Bağlamak için yönetici yetkisi gerekir.</p>}
      {state.last_error && <p className="text-rose-700">{state.last_error}</p>}
      {msg && <p role="status" className={msg.ok ? "text-emerald-700" : "text-yt"}>{msg.text}</p>}
    </div>
  );
}
