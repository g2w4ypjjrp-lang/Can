"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { API_URL } from "@/lib/env";
import { supabaseBrowser } from "@/lib/supabase/client";

export function ApprovalActions({ id }: { id: string }) {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function decide(approve: boolean) {
    if (!approve && !note.trim()) return setErr("Reddetmek için neden yazın.");
    if (approve && !confirm("Bu işlemi onaylıyor musunuz?")) return;
    setBusy(true); setErr(null);
    const { data } = await supabaseBrowser().auth.getSession();
    const r = await fetch(`${API_URL}/api/approvals/${id}/decision`, {
      method: "POST",
      headers: { authorization: `Bearer ${data.session?.access_token ?? ""}`, "content-type": "application/json" },
      body: JSON.stringify({ approve, note: note.trim() || null }),
    });
    setBusy(false);
    if (!r.ok) return setErr((await r.json().catch(() => ({}))).detail ?? "Hata");
    router.refresh();
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Not / ret nedeni" maxLength={2000}
        className="min-w-0 flex-1 rounded-lg border border-line bg-transparent px-3 py-2 text-sm" />
      <button disabled={busy} onClick={() => decide(false)} className="rounded-lg border border-line px-4 py-2 text-sm">Reddet</button>
      <button disabled={busy} onClick={() => decide(true)} className="rounded-lg bg-brand px-4 py-2 text-sm text-white">Onayla</button>
      {err && <p role="alert" className="w-full text-sm text-yt">{err}</p>}
    </div>
  );
}
