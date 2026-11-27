import Link from "next/link";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type Run = { id: string; task_id: string | null; agent: string; status: string; model: string | null;
  input_tokens: number | null; output_tokens: number | null; cost_usd: string | null; error: string | null;
  started_at: string; finished_at: string | null };

export default async function Logs() {
  const { token, org } = await appContext();
  const runs = await api<Run[]>(`/api/organizations/${org.id}/agent-runs`, token);
  const total = runs.reduce((s, r) => s + Number(r.cost_usd ?? 0), 0);
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">System Logs</h1>
        <p className="text-sm text-muted">Ajan çalıştırmaları, token kullanımı ve maliyet. Son {runs.length} kayıt: ${total.toFixed(4)}</p>
      </header>
      <div className="overflow-x-auto rounded-2xl border border-line bg-panel">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="text-left text-xs text-muted"><tr>
            {["Zaman", "Ajan", "Durum", "Model", "Token (girdi/çıktı)", "Maliyet", "Görev"].map((h) => <th key={h} className="p-3 font-medium">{h}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-line">
            {runs.map((r) => (
              <tr key={r.id}>
                <td className="p-3 whitespace-nowrap">{new Date(r.started_at).toLocaleString("tr-TR")}</td>
                <td className="p-3">{r.agent}</td>
                <td className="p-3"><StatusBadge status={r.status} />{r.error && <div className="text-xs text-rose-700">{r.error}</div>}</td>
                <td className="p-3 text-muted">{r.model}</td>
                <td className="p-3 tabular-nums">{r.input_tokens ?? "—"} / {r.output_tokens ?? "—"}</td>
                <td className="p-3 tabular-nums">{r.cost_usd ? `$${Number(r.cost_usd).toFixed(4)}` : "—"}</td>
                <td className="p-3">{r.task_id && <Link className="text-brand underline" href={`/tasks/${r.task_id}`}>Aç</Link>}</td>
              </tr>
            ))}
            {!runs.length && <tr><td colSpan={7} className="p-6 text-center text-muted">Henüz kayıt yok.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
