import { notFound } from "next/navigation";
import { AutoRefresh } from "@/components/AutoRefresh";
import { CancelButton } from "@/components/CancelButton";
import { Markdownish } from "@/components/Markdownish";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError } from "@/lib/api";
import { appContext } from "@/lib/context";
import { ACTIVE } from "@/lib/tasks";

type Step = { position: number; description: string; status: string; agent: string;
  output: { text: string; sources: { url: string; title: string }[]; cost_usd: string } | null };
type Run = { id: string; agent: string; status: string; input_tokens: number | null; output_tokens: number | null;
  cost_usd: string | null; error: string | null };
type Task = { id: string; title: string; command: string; status: string; error: string | null; current_agent: string | null;
  result: { plan_summary?: string; report?: string; total_cost_usd?: string } | null; steps: Step[]; runs: Run[] };

export default async function TaskDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { token, org } = await appContext();
  let t: Task;
  try { t = await api<Task>(`/api/tasks/${encodeURIComponent(id)}`, token); }
  catch (e) { if (e instanceof ApiError && (e.status === 404 || e.status === 422)) notFound(); throw e; }
  const active = ACTIVE.has(t.status);
  const cost = t.runs.reduce((s, r) => s + Number(r.cost_usd ?? 0), 0);

  return (
    <div className="max-w-4xl space-y-6">
      {active && <AutoRefresh seconds={3} />}
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={t.status} />
          {active && t.current_agent && <span className="text-sm text-muted">Şu an: {t.current_agent}</span>}
          <span className="ml-auto text-sm text-muted">Maliyet: ${cost.toFixed(4)}</span>
          {active && (org.role === "owner" || org.role === "admin") && <CancelButton id={t.id} />}
        </div>
        <h1 className="text-xl font-semibold">{t.title}</h1>
        <p className="whitespace-pre-wrap text-sm text-muted">{t.command}</p>
        {t.error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{t.error}</p>}
      </header>

      {t.result?.report && (
        <section className="rounded-2xl border border-line bg-panel p-5">
          <h2 className="mb-3 font-semibold">CEO raporu</h2>
          <Markdownish text={t.result.report} />
        </section>
      )}

      <section>
        <h2 className="mb-3 font-semibold">Plan {t.result?.plan_summary && <span className="font-normal text-muted">· {t.result.plan_summary}</span>}</h2>
        {t.steps.length === 0 && <p className="text-sm text-muted">{active ? "CEO planlıyor…" : "Plan yok."}</p>}
        <ol className="space-y-3">
          {t.steps.map((s) => (
            <li key={s.position} className="rounded-xl border border-line bg-panel p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted">#{s.position}</span>
                <span className="font-medium">{s.agent}</span>
                <StatusBadge status={s.status} />
              </div>
              <p className="mt-1 text-sm text-muted">{s.description}</p>
              {s.output && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-sm text-brand">Çıktıyı göster</summary>
                  <div className="mt-2"><Markdownish text={s.output.text} /></div>
                  {s.output.sources.length > 0 && (
                    <ul className="mt-2 space-y-1 text-xs">
                      {s.output.sources.map((src) => (
                        <li key={src.url}><a href={src.url} target="_blank" rel="noopener noreferrer nofollow"
                          className="text-brand underline">{src.title || src.url}</a></li>))}
                    </ul>
                  )}
                </details>
              )}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
