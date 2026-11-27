import Link from "next/link";
import { StatusBadge } from "./StatusBadge";
import type { TaskRow } from "@/lib/tasks";

export function TaskList({ tasks }: { tasks: TaskRow[] }) {
  if (!tasks.length) return <p className="rounded-xl border border-line bg-panel p-6 text-sm text-muted">Henüz görev yok.</p>;
  return (
    <ul className="divide-y divide-line rounded-2xl border border-line bg-panel">
      {tasks.map((t) => (
        <li key={t.id}>
          <Link href={`/tasks/${t.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-4 hover:bg-canvas">
            <span className="min-w-0 flex-1 basis-full truncate font-medium sm:basis-auto">{t.title}</span>
            <StatusBadge status={t.status} />
            <span className="text-xs text-muted">
              {t.current_agent && t.status === "running" ? `${t.current_agent} · ` : ""}
              {t.cost_usd ? `$${Number(t.cost_usd).toFixed(4)} · ` : ""}
              {new Date(t.created_at).toLocaleString("tr-TR")}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
