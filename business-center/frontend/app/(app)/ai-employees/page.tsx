import { StarterPack } from "@/components/StarterPack";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type Agent = { id: string; code: string; name: string; description: string; enabled: boolean;
  department: string; department_name: string; active_tasks: number };

const ORDER = ["executive", "youtube", "etsy", "quality"];
const TONE: Record<string, string> = { executive: "bg-brand", youtube: "bg-yt", etsy: "bg-etsy", quality: "bg-emerald-600" };

export default async function Employees() {
  const { token, org } = await appContext();
  const [agents, starter, status, prof] = await Promise.all([
    api<Agent[]>(`/api/organizations/${org.id}/agents`, token),
    api<Record<string, string>>(`/api/agents/starter-tasks`, token),
    api<{ llm_configured: boolean; max_task_cost_usd: number; max_parallel_tasks: number }>(`/api/system/status`, token),
    api<{ profile: Record<string, string> | null }>(`/api/organizations/${org.id}/profile`, token),
  ]);
  const profileReady = !!(prof.profile?.youtube_niche || prof.profile?.etsy_niche);
  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">AI Employees</h1>
        <p className="text-sm text-muted">{agents.length} uzman ajan. Her biri kendi alanında çalışma yöntemi, çıktı şablonu ve kontrol listesiyle çalışır.</p>
      </header>
      {org.role !== "viewer" && (
        <StarterPack orgId={org.id} agents={agents} tasks={starter} maxCost={status.max_task_cost_usd}
          maxParallel={status.max_parallel_tasks} ready={{ llm: status.llm_configured, profile: profileReady }} />
      )}
      {ORDER.map((dep) => {
        const list = agents.filter((a) => a.department === dep);
        if (!list.length) return null;
        return (
          <section key={dep}>
            <h2 className="mb-3 flex items-center gap-2 font-semibold">
              <span className={`h-2.5 w-2.5 rounded-full ${TONE[dep]}`} />{list[0].department_name}
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {list.map((a) => (
                <article key={a.id} className="rounded-xl border border-line bg-panel p-4">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="font-medium">{a.name}</h3>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] ${a.active_tasks ? "bg-emerald-100 text-emerald-800" : "bg-canvas text-muted"}`}>
                      {a.active_tasks ? `${a.active_tasks} görev` : "Boşta"}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-muted">{a.description}</p>
                </article>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
