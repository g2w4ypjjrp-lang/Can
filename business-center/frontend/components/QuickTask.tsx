"use client";
import Link from "next/link";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";

/** Bir ajana tek tıkla hazır görev verir (doğrudan atama, CEO planı yok). */
export function QuickTask({ orgId, agent, command, label }: { orgId: string; agent: string; command: string; label: string }) {
  const [state, setState] = useState<{ id?: string; err?: string; busy?: boolean }>({});
  async function go() {
    if (!confirm(`"${command}"\n\nBu görev ücretli bir model çağrısı yapar. Başlatılsın mı?`)) return;
    setState({ busy: true });
    const r = await clientApi(`/api/organizations/${orgId}/tasks`, { method: "POST", body: JSON.stringify({ command, agent_code: agent }) });
    setState(r.ok ? { id: r.data.id } : { err: r.error });
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button type="button" onClick={go} disabled={state.busy}
        className="rounded-xl border border-line bg-panel px-3 py-1.5 text-sm hover:bg-canvas disabled:opacity-60">{label}</button>
      {state.id && <Link href={`/tasks/${state.id}`} className="text-xs text-brand underline">Görevi izle</Link>}
      {state.err && <span className="text-xs text-yt">{state.err}</span>}
    </span>
  );
}
