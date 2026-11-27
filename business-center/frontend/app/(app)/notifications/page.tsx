import Link from "next/link";
import { MarkAllRead } from "@/components/MarkAllRead";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type N = { id: string; kind: string; title: string; body: string; link: string | null; read_at: string | null; created_at: string };

export default async function Notifications() {
  const { token, org } = await appContext();
  const { unread, items } = await api<{ unread: number; items: N[] }>(`/api/organizations/${org.id}/notifications`, token);
  return (
    <div className="max-w-3xl space-y-6">
      <header className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Notifications</h1>
        <span className="text-sm text-muted">{unread} okunmamış</span>
        {unread > 0 && <span className="ml-auto"><MarkAllRead orgId={org.id} /></span>}
      </header>
      <ul className="divide-y divide-line rounded-2xl border border-line bg-panel">
        {!items.length && <li className="p-6 text-sm text-muted">Bildirim yok.</li>}
        {items.map((n) => {
          const body = (
            <div className="flex gap-3 p-4">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read_at ? "bg-transparent" : "bg-brand"}`} />
              <div className="min-w-0">
                <p className="font-medium">{n.title}</p>
                {n.body && <p className="text-sm text-muted">{n.body}</p>}
                <p className="text-xs text-muted">{new Date(n.created_at).toLocaleString("tr-TR")}</p>
              </div>
            </div>
          );
          return <li key={n.id}>{n.link?.startsWith("/") ? <Link href={n.link} className="block hover:bg-canvas">{body}</Link> : body}</li>;
        })}
      </ul>
    </div>
  );
}
