import Link from "next/link";
import { PageHeader } from "@/components/Page";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type Ev = { kind: "video" | "task" | "automation"; title: string; at: string; status: string };
const KIND: Record<Ev["kind"], { label: string; cls: string }> = {
  video: { label: "Video", cls: "bg-rose-100 text-rose-800" },
  task: { label: "Görev", cls: "bg-indigo-100 text-indigo-800" },
  automation: { label: "Planlı", cls: "bg-amber-100 text-amber-900" },
};
const DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

export default async function Calendar({ searchParams }: { searchParams: Promise<{ month?: string }> }) {
  const { token, org } = await appContext();
  const sp = await searchParams;
  const now = new Date();
  const month = /^\d{4}-\d{2}$/.test(sp.month ?? "") ? sp.month! : `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [y, m] = month.split("-").map(Number);
  const evs = await api<Ev[]>(`/api/organizations/${org.id}/calendar?month=${month}`, token);
  const first = new Date(y, m - 1, 1), daysIn = new Date(y, m, 0).getDate(), offset = (first.getDay() + 6) % 7;
  const byDay = new Map<number, Ev[]>();
  for (const e of evs) { const d = new Date(e.at); if (d.getMonth() === m - 1) byDay.set(d.getDate(), [...(byDay.get(d.getDate()) ?? []), e]); }
  const shift = (k: number) => { const d = new Date(y, m - 1 + k, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
  const today = now.getFullYear() === y && now.getMonth() === m - 1 ? now.getDate() : -1;

  return (
    <div className="max-w-6xl space-y-4">
      <PageHeader title="Content Calendar" desc="Yayınlanan videolar, görevler ve planlı otomasyonlar.">
        <Link href={`/calendar?month=${shift(-1)}`} className="rounded-lg border border-line px-3 py-1.5 text-sm">←</Link>
        <span className="px-2 py-1.5 text-sm font-medium">{first.toLocaleDateString("tr-TR", { month: "long", year: "numeric" })}</span>
        <Link href={`/calendar?month=${shift(1)}`} className="rounded-lg border border-line px-3 py-1.5 text-sm">→</Link>
      </PageHeader>
      <div className="flex flex-wrap gap-3 text-xs">{Object.values(KIND).map((k) => <span key={k.label} className={`rounded-full px-2 py-0.5 ${k.cls}`}>{k.label}</span>)}</div>
      <div className="overflow-x-auto">
        <div className="grid min-w-[700px] grid-cols-7 gap-px overflow-hidden rounded-2xl border border-line bg-line">
          {DAYS.map((d) => <div key={d} className="bg-panel p-2 text-center text-xs font-medium text-muted">{d}</div>)}
          {Array.from({ length: offset }).map((_, i) => <div key={`e${i}`} className="bg-canvas" />)}
          {Array.from({ length: daysIn }, (_, i) => i + 1).map((day) => (
            <div key={day} className="min-h-24 bg-panel p-1.5">
              <div className={`mb-1 inline-flex h-6 w-6 items-center justify-center rounded-full text-xs ${day === today ? "bg-brand text-white" : "text-muted"}`}>{day}</div>
              <ul className="space-y-1">{(byDay.get(day) ?? []).slice(0, 3).map((e, i) => (
                <li key={i} title={e.title} className={`truncate rounded px-1.5 py-0.5 text-[11px] ${KIND[e.kind].cls}`}>{e.title}</li>))}
                {(byDay.get(day)?.length ?? 0) > 3 && <li className="text-[11px] text-muted">+{byDay.get(day)!.length - 3}</li>}
              </ul>
            </div>
          ))}
          {Array.from({ length: (7 - ((offset + daysIn) % 7)) % 7 }).map((_, i) => <div key={`t${i}`} className="bg-canvas" />)}
        </div>
      </div>
    </div>
  );
}
