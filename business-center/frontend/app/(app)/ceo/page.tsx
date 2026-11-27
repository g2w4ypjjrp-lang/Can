import { CommandBox } from "@/components/CommandBox";
import { TaskList } from "@/components/TaskList";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";
import type { TaskRow } from "@/lib/tasks";

export default async function Ceo() {
  const { token, org } = await appContext();
  const tasks = await api<TaskRow[]>(`/api/organizations/${org.id}/tasks`, token);
  const canCommand = org.role === "owner" || org.role === "admin";
  return (
    <div className="max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">CEO Command Center</h1>
        <p className="text-sm text-muted">
          CEO Agent komutunuzu planlar, uzman ajanlara dağıtır ve tek rapor sunar. Ajanlar platformlarınızda
          hiçbir şeyi yayınlamaz veya değiştirmez; bu tür işlemler onayınıza sunulur. Her görevin bir maliyet üst sınırı vardır.
        </p>
      </header>
      {canCommand ? <CommandBox orgId={org.id} /> : <p className="text-sm text-muted">Görev vermek için yönetici yetkisi gerekir.</p>}
      <section>
        <h2 className="mb-3 font-semibold">Son görevler</h2>
        <TaskList tasks={tasks.slice(0, 10)} />
      </section>
    </div>
  );
}
