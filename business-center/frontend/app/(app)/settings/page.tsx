import { ProfileForm } from "@/components/ProfileForm";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type Status = { llm_configured: boolean; model: string; max_task_cost_usd: number; max_parallel_tasks: number };

export default async function Settings() {
  const { token, org } = await appContext();
  const [{ profile }, status] = await Promise.all([
    api<{ profile: Record<string, string> | null }>(`/api/organizations/${org.id}/profile`, token),
    api<Status>(`/api/system/status`, token),
  ]);
  return (
    <div className="max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted">İşletme profili her ajana her görevde verilir. Ne kadar net doldurursanız sonuçlar o kadar isabetli olur.</p>
      </header>
      <section className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-line bg-panel p-4">
          <p className="text-xs text-muted">Claude API</p>
          <p className={`mt-1 font-semibold ${status.llm_configured ? "text-emerald-700" : "text-yt"}`}>
            {status.llm_configured ? "Bağlı" : "Anahtar yok (BC_ANTHROPIC_API_KEY)"}</p>
          <p className="text-xs text-muted">Model: {status.model}</p>
        </div>
        <div className="rounded-2xl border border-line bg-panel p-4">
          <p className="text-xs text-muted">Görev başına harcama üst sınırı</p>
          <p className="mt-1 font-semibold">${status.max_task_cost_usd.toFixed(2)}</p>
        </div>
        <div className="rounded-2xl border border-line bg-panel p-4">
          <p className="text-xs text-muted">Aynı anda çalışan görev</p>
          <p className="mt-1 font-semibold">{status.max_parallel_tasks}</p>
        </div>
      </section>
      <h2 className="text-lg font-semibold">İşletme Profili</h2>
      <ProfileForm orgId={org.id} initial={profile} canEdit={org.role !== "viewer"} />
    </div>
  );
}
