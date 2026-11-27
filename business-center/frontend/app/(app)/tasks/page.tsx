import { TaskList } from "@/components/TaskList";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";
import type { TaskRow } from "@/lib/tasks";

export default async function Tasks() {
  const { token, org } = await appContext();
  const tasks = await api<TaskRow[]>(`/api/organizations/${org.id}/tasks`, token);
  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">Task Management</h1>
      <TaskList tasks={tasks} />
    </div>
  );
}
