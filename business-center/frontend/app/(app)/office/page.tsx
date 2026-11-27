import { Office } from "@/components/Office";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";
import type { Agent } from "@/lib/office";
import type { TaskRow } from "@/lib/tasks";

export default async function OfficePage() {
  const { token, org } = await appContext();
  const [agents, tasks] = await Promise.all([
    api<Agent[]>(`/api/organizations/${org.id}/agents`, token),
    api<TaskRow[]>(`/api/organizations/${org.id}/tasks`, token),
  ]);
  return <Office orgId={org.id} initialAgents={agents} initialTasks={tasks}
    canCommand={org.role === "owner" || org.role === "admin"} />;
}
