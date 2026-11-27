import { AutomationManager } from "@/components/AutomationManager";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

export default async function Automation() {
  const { token, org } = await appContext();
  const [rules, templates] = await Promise.all([
    api<any[]>(`/api/organizations/${org.id}/automation`, token),
    api<any[]>(`/api/automation/templates`, token),
  ]);
  return (
    <div className="max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Automation</h1>
        <p className="text-sm text-muted">
          Zamanlanmış görevler CEO'ya otomatik komut verir. Her çalıştırma ücretli model çağrısı yapar; bu yüzden kurallar
          kapalı eklenir, siz açarsınız. Zamanlanmış görevler de onay kurallarını aşamaz.
        </p>
      </header>
      <AutomationManager orgId={org.id} rules={rules} templates={templates} canEdit={org.role !== "viewer"} />
    </div>
  );
}
