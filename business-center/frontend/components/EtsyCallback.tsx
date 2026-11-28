"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { clientApi } from "@/lib/client-api";

export function EtsyCallback({ orgId }: { orgId: string }) {
  const q = useSearchParams();
  const done = useRef(false);
  const [state, setState] = useState<{ ok: boolean | null; text: string }>({ ok: null, text: "Etsy bağlantısı tamamlanıyor…" });
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const err = q.get("error"), code = q.get("code"), st = q.get("state");
    if (err || !code || !st) { setState({ ok: false, text: err === "access_denied" ? "Etsy izni verilmedi." : "Etsy'den geçerli yanıt gelmedi." }); return; }
    clientApi(`/api/organizations/${orgId}/integrations/etsy/callback`, { method: "POST", body: JSON.stringify({ code, state: st }) })
      .then((r) => setState(r.ok ? { ok: true, text: `Bağlandı: ${r.data.shop.name}` } : { ok: false, text: r.error ?? "Bağlanamadı" }));
  }, [orgId, q]);
  return (
    <div className="max-w-md rounded-2xl border border-line bg-panel p-6">
      <h1 className="text-lg font-semibold">Etsy bağlantısı</h1>
      <p role="status" className={`mt-2 text-sm ${state.ok === false ? "text-yt" : state.ok ? "text-emerald-700" : "text-muted"}`}>{state.text}</p>
      {state.ok !== null && <Link href="/integrations" className="mt-4 inline-block text-sm text-brand underline">API Integrations'a dön</Link>}
    </div>
  );
}
