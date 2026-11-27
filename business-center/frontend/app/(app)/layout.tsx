import { Sidebar } from "@/components/Sidebar";
import { SetupRequired } from "@/components/SetupRequired";
import { appContext } from "@/lib/context";
import { isConfigured } from "@/lib/env";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  if (!isConfigured()) return <SetupRequired />;
  const { me, org } = await appContext();
  return (
    <div className="md:flex">
      <Sidebar orgName={org.name} email={me.email} />
      <main className="min-w-0 flex-1 p-4 md:p-8">{children}</main>
    </div>
  );
}
