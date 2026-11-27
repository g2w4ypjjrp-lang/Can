"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { API_URL } from "@/lib/env";
import { supabaseBrowser } from "@/lib/supabase/client";

const EXAMPLES = [
  "Bu hafta YouTube için 5 video fikri bul.",
  "Etsy mağazamda satış potansiyeli olan 20 ürün araştır.",
  "Yeni bir video hazırla ama yayınlamadan önce bana göster.",
  "Printify maliyetlerini kontrol et ve kâr marjı düşük ürünleri bul.",
  "Bugün iki departmanın da günlük raporunu hazırla.",
];

export function CommandBox({ orgId }: { orgId: string }) {
  const router = useRouter();
  const [cmd, setCmd] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (cmd.trim().length < 3) return;
    setBusy(true); setErr(null);
    const { data } = await supabaseBrowser().auth.getSession();
    const r = await fetch(`${API_URL}/api/organizations/${orgId}/tasks`, {
      method: "POST",
      headers: { authorization: `Bearer ${data.session?.access_token ?? ""}`, "content-type": "application/json" },
      body: JSON.stringify({ command: cmd.trim() }),
    });
    setBusy(false);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return setErr(typeof body.detail === "string" ? body.detail : "Görev oluşturulamadı");
    router.push(`/tasks/${body.id}`);
  }

  return (
    <form onSubmit={submit} className="rounded-2xl border border-line bg-panel p-4 shadow-sm">
      <textarea value={cmd} onChange={(e) => setCmd(e.target.value)} rows={3} maxLength={4000}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit(); }}
        placeholder="Ekibine bir görev ver…" aria-label="CEO'ya komut"
        className="w-full resize-none bg-transparent outline-none" />
      <div className="mt-2 flex flex-wrap gap-2">
        {EXAMPLES.map((x) => (
          <button type="button" key={x} onClick={() => setCmd(x)}
            className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:bg-canvas">{x}</button>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <span className="text-xs text-muted">Ctrl + Enter</span>
        {err && <span role="alert" className="text-sm text-yt">{err}</span>}
        <button disabled={busy} className="ml-auto rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-60">
          {busy ? "Gönderiliyor…" : "Görevi ver →"}
        </button>
      </div>
    </form>
  );
}
