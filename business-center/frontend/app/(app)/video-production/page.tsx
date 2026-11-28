import Link from "next/link";
import { PageHeader } from "@/components/Page";
import { QuickTask } from "@/components/QuickTask";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type P = { ideas: { id: string; title: string }[]; scripts: { id: string; hook: string; qc_status: string }[];
  videos: { youtube_video_id: string | null; title: string; lifecycle: string }[];
  tasks: { id: string; title: string; status: string; agent: string }[] };

const STAGES: [string, string][] = [["idea", "Fikir"], ["scripting", "Senaryo"], ["production", "Üretim"], ["review", "İnceleme / Onay"], ["published", "Yayında"]];

export default async function Production() {
  const { token, org } = await appContext();
  const d = await api<P>(`/api/organizations/${org.id}/production`, token);
  const admin = org.role !== "viewer";
  const col = (k: string) => [
    ...(k === "idea" ? d.ideas.map((i) => i.title) : []),
    ...(k === "scripting" ? d.scripts.map((s) => s.hook || "Senaryo") : []),
    ...d.videos.filter((v) => v.lifecycle === k).map((v) => v.title)];
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader title="Video Production" desc="Fikirden yayına üretim hattı. Yayın her zaman onayınızla yapılır.">
        {admin && <QuickTask orgId={org.id} agent="yt_script_writer" label="Senaryo yaz"
          command="Kanalım için en yüksek potansiyelli konuda 8-10 dakikalık video senaryosu ve Shorts versiyonu yaz." />}
      </PageHeader>
      <div className="grid gap-3 md:grid-cols-5">
        {STAGES.map(([k, label]) => {
          const items = col(k);
          return (
            <section key={k} className="rounded-2xl border border-line bg-panel p-3">
              <h2 className="mb-2 flex items-center justify-between text-sm font-semibold">{label}<span className="text-xs text-muted">{items.length}</span></h2>
              <ul className="space-y-2">
                {items.slice(0, 8).map((t, i) => <li key={i} className="rounded-lg bg-canvas p-2 text-xs">{t}</li>)}
                {!items.length && <li className="text-xs text-muted">Boş</li>}
              </ul>
            </section>
          );
        })}
      </div>
      <section>
        <h2 className="mb-3 font-semibold">YouTube ekibinin son görevleri</h2>
        <ul className="divide-y divide-line rounded-2xl border border-line bg-panel">
          {d.tasks.map((t) => (
            <li key={t.id}><Link href={`/tasks/${t.id}`} className="flex items-center gap-3 p-3 text-sm hover:bg-canvas">
              <StatusBadge status={t.status} /><span className="min-w-0 flex-1 truncate">{t.title}</span><span className="text-xs text-muted">{t.agent}</span>
            </Link></li>
          ))}
          {!d.tasks.length && <li className="p-4 text-sm text-muted">Henüz görev yok.</li>}
        </ul>
      </section>
    </div>
  );
}
