"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

type Shop = { id: number; title: string };
type State = { status: string; display_name?: string | null; last_error?: string | null; last_synced_at?: string | null; product_count?: number };

export function PrintifyCard({ orgId, state, canEdit }: { orgId: string; state: State; canEdit: boolean }) {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [shops, setShops] = useState<Shop[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const base = `/api/organizations/${orgId}/integrations/printify`;
  const connected = state.status === "connected";

  async function connect(shopId?: number) {
    setBusy(true); setMsg(null);
    const { data } = await import("@/lib/supabase/client").then((m) => m.supabaseBrowser().auth.getSession());
    const r = await fetch((await import("@/lib/env")).API_URL + base, {
      method: "POST", headers: { authorization: `Bearer ${data.session?.access_token ?? ""}`, "content-type": "application/json" },
      body: JSON.stringify({ token: token.trim(), shop_id: shopId ?? null }) });
    const body = await r.json().catch(() => ({}));
    setBusy(false);
    if (r.status === 409 && body.detail?.shops) { setShops(body.detail.shops); return; }
    if (!r.ok) return setMsg({ ok: false, text: typeof body.detail === "string" ? body.detail : "Bağlanamadı" });
    setToken(""); setShops(null); setMsg({ ok: true, text: `Bağlandı: ${body.shop.title}` }); router.refresh();
  }
  async function act(path: string, method: string, okText: (d: any) => string) {
    setBusy(true); setMsg(null);
    const r = await clientApi(base + path, { method });
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: okText(r.data) } : { ok: false, text: r.error ?? "Hata" }); router.refresh();
  }

  return (
    <div className="space-y-3">
      {connected ? (
        <div className="text-sm">
          <p>Mağaza: <b>{state.display_name}</b> · {state.product_count ?? 0} ürün</p>
          <p className="text-xs text-muted">Son senkron: {state.last_synced_at ? new Date(state.last_synced_at).toLocaleString("tr-TR") : "henüz yok"}</p>
          {canEdit && (
            <div className="mt-3 flex gap-2">
              <button disabled={busy} onClick={() => act("/sync", "POST", (d) => `${d.synced} ürün senkronlandı`)}
                className="rounded-xl bg-brand px-4 py-2 text-sm text-white disabled:opacity-60">{busy ? "Çalışıyor…" : "Ürünleri senkronla"}</button>
              <button disabled={busy} onClick={() => confirm("Printify bağlantısı kesilsin ve token silinsin mi?") && act("", "DELETE", () => "Bağlantı kesildi")}
                className="rounded-xl border border-line px-4 py-2 text-sm">Bağlantıyı kes</button>
            </div>
          )}
        </div>
      ) : canEdit ? (
        <form onSubmit={(e) => { e.preventDefault(); connect(); }} className="space-y-2">
          <label className="block text-sm"><span className="text-muted">Kişisel erişim token'ı</span>
            <input type="password" autoComplete="off" required minLength={20} value={token} onChange={(e) => setToken(e.target.value)}
              placeholder="Printify > My Profile > Connections > Personal access tokens"
              className="mt-1 w-full rounded-xl border border-line bg-transparent px-3 py-2 text-sm" />
          </label>
          <p className="text-xs text-muted">Gereken izinler: shops.read, products.read, orders.read, catalog.read. Token sunucuda şifreli saklanır, size geri gösterilmez.</p>
          <button disabled={busy} className="rounded-xl bg-brand px-4 py-2 text-sm text-white disabled:opacity-60">{busy ? "Doğrulanıyor…" : "Bağla"}</button>
        </form>
      ) : <p className="text-sm text-muted">Bağlamak için yönetici yetkisi gerekir.</p>}
      {shops && (
        <div className="rounded-xl border border-line p-3 text-sm">
          <p className="mb-2">Hangi mağaza?</p>
          <div className="flex flex-wrap gap-2">{shops.map((s) => (
            <button key={s.id} onClick={() => connect(s.id)} className="rounded-lg border border-line px-3 py-1.5 hover:bg-canvas">{s.title}</button>))}
          </div>
        </div>
      )}
      {state.last_error && <p className="text-sm text-rose-700">{state.last_error}</p>}
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-emerald-700" : "text-yt"}`}>{msg.text}</p>}
    </div>
  );
}
