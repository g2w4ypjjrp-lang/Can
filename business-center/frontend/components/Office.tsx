"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { clientApi } from "@/lib/client-api";
import { ROOMS, shortName, type Agent, type Room } from "@/lib/office";
import { ACTIVE, STATUS, type TaskRow } from "@/lib/tasks";
import { StatusBadge } from "./StatusBadge";

const FLOOR_W = 1240, FLOOR_H = 820, GAP = 22, PAD = 30;
const ROOM_W = (FLOOR_W - PAD * 2 - GAP * 3) / 4, ROOM_H = (FLOOR_H - PAD * 2 - GAP) / 2;

export function Office({ orgId, initialAgents, initialTasks, canCommand }:
  { orgId: string; initialAgents: Agent[]; initialTasks: TaskRow[]; canCommand: boolean }) {
  const [agents, setAgents] = useState(initialAgents);
  const [tasks, setTasks] = useState(initialTasks);
  const [target, setTarget] = useState("ceo");
  const [tab, setTab] = useState<"tasks" | "team">("tasks");

  // Canlı durum: aktif görev varken 3 sn, yokken 15 sn'de bir yenile.
  const busy = tasks.some((t) => ACTIVE.has(t.status));
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      const [a, t] = await Promise.all([
        clientApi(`/api/organizations/${orgId}/agents`), clientApi(`/api/organizations/${orgId}/tasks`)]);
      if (stop) return;
      if (a.ok) setAgents(a.data);
      if (t.ok) setTasks(t.data);
    };
    const id = setInterval(tick, busy ? 3000 : 15000);
    return () => { stop = true; clearInterval(id); };
  }, [orgId, busy]);

  const byCode = useMemo(() => Object.fromEntries(agents.map((a) => [a.code, a])), [agents]);
  const working = agents.filter((a) => a.active_tasks > 0).length;

  return (
    <div className="relative -m-4 min-h-[calc(100vh-0px)] overflow-hidden bg-[#eef0f4] md:-m-8 dark:bg-[#0f131c]">
      <div className="flex flex-col xl:flex-row">
        <div className="relative min-w-0 flex-1 pb-44">
          <header className="flex items-center gap-3 px-4 pt-4 md:px-8 md:pt-6">
            <p className="text-[11px] font-semibold tracking-[.3em] text-muted">AI OFİS</p>
            <span className="rounded-full bg-panel px-3 py-1 text-xs shadow-sm">
              <span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${working ? "animate-pulse bg-emerald-500" : "bg-slate-300"}`} />
              {working ? `${working} ajan çalışıyor` : "Ekip hazır"} · {agents.length} ajan
            </span>
          </header>
          <IsoFloor byCode={byCode} target={target} onPick={canCommand ? setTarget : undefined} />
          <FlatFloor byCode={byCode} target={target} onPick={canCommand ? setTarget : undefined} />
        </div>
        <SidePanel tab={tab} setTab={setTab} tasks={tasks} agents={agents} />
      </div>
      {canCommand && <CommandBar orgId={orgId} agents={agents} target={target} setTarget={setTarget}
        onSent={(t) => setTasks((prev) => [t, ...prev])} />}
    </div>
  );
}

/* ---------------- izometrik ofis (md ve üstü) ---------------- */

function IsoFloor({ byCode, target, onPick }: { byCode: Record<string, Agent>; target: string; onPick?: (c: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.8);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setScale(Math.min(1.1, e.contentRect.width / 1580)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={box} className="relative hidden h-[600px] md:block lg:h-[720px]" aria-label="Ofis yerleşimi">
      <div className="absolute left-[49%] top-[48%]" style={{ transform: `translate(-50%,-50%) scale(${scale})` }}>
        <div className="iso-floor" style={{ width: FLOOR_W, height: FLOOR_H }}>
          <div className="iso-wall iso-wall-n">
            {[0.12, 0.32, 0.52, 0.72].map((f) => <span key={f} className="iso-window" style={{ left: `${f * 100}%` }} />)}
          </div>
          <div className="iso-wall iso-wall-w">
            {[0.15, 0.55].map((f) => <span key={f} className="iso-window" style={{ top: `${f * 100}%`, left: 14, width: 52, height: 70 }} />)}
          </div>
          {ROOMS.map((r) => <IsoRoom key={r.key} room={r} byCode={byCode} target={target} onPick={onPick} />)}
        </div>
      </div>
    </div>
  );
}

function IsoRoom({ room, byCode, target, onPick }: { room: Room; byCode: Record<string, Agent>; target: string; onPick?: (c: string) => void }) {
  const left = PAD + room.col * (ROOM_W + GAP), top = PAD + room.row * (ROOM_H + GAP);
  const members = room.codes.map((c) => byCode[c]).filter(Boolean);
  const cols = Math.min(3, members.length);
  return (
    <div className="iso-room" style={{ left, top, width: ROOM_W, height: ROOM_H }}>
      <div className="iso-glass iso-glass-n" /><div className="iso-glass iso-glass-s" />
      <div className="iso-glass iso-glass-w" /><div className="iso-glass iso-glass-e" />
      <div className="iso-plant" style={{ left: ROOM_W - 30, top: 12 }} />
      <div className="iso-billboard" style={{ left: 70, top: ROOM_H - 14 }}>
        <span className="iso-room-label" style={{ borderLeftColor: room.tone }}>{room.label}</span>
      </div>
      {members.map((a, i) => {
        const col = i % cols, row = Math.floor(i / cols), rows = Math.ceil(members.length / cols);
        const x = (ROOM_W / (cols + 1)) * (col + 1) + (row % 2 ? 18 : 0), y = 30 + ((ROOM_H - 60) / (rows + 1)) * (row + 1);
        return <Desk key={a.id} agent={a} x={x} y={y} tone={room.tone} selected={target === a.code} onPick={onPick} />;
      })}
    </div>
  );
}

function Desk({ agent, x, y, tone, selected, onPick }:
  { agent: Agent; x: number; y: number; tone: string; selected: boolean; onPick?: (c: string) => void }) {
  const on = agent.active_tasks > 0;
  return (
    <>
      <div className="iso-desk" style={{ left: x - 30, top: y - 38 }}><div className={`iso-monitor ${on ? "is-on" : ""}`} /></div>
      <div className="iso-billboard" style={{ left: x, top: y - 14 }}>
        <button type="button" onClick={() => onPick?.(agent.code)} disabled={!onPick}
          title={`${agent.name}: ${agent.description}`}
          className={`iso-person ${on ? "is-working" : ""}`} style={{ ["--tone" as string]: tone }}>
          <span className="iso-head" /><span className="iso-body" />
        </button>
        <span className={`iso-chip ${selected ? "is-selected" : ""}`}>
          <i className={on ? "bg-emerald-500 animate-pulse" : "bg-slate-300"} />{shortName(agent.name)}
        </span>
        {on && <span className="iso-bubble">çalışıyor…</span>}
      </div>
    </>
  );
}

/* ---------------- düz görünüm (telefon) ---------------- */

function FlatFloor({ byCode, target, onPick }: { byCode: Record<string, Agent>; target: string; onPick?: (c: string) => void }) {
  return (
    <div className="grid gap-3 p-4 sm:grid-cols-2 md:hidden">
      {ROOMS.map((r) => (
        <section key={r.key} className="rounded-2xl border border-line bg-panel p-3" style={{ borderTop: `3px solid ${r.tone}` }}>
          <h2 className="text-[11px] font-semibold tracking-wider text-muted">{r.label}</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {r.codes.map((c) => byCode[c]).filter(Boolean).map((a) => (
              <button key={a.id} type="button" disabled={!onPick} onClick={() => onPick?.(a.code)}
                className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${target === a.code ? "border-brand" : "border-line"}`}>
                <i className={`h-2 w-2 rounded-full ${a.active_tasks ? "animate-pulse bg-emerald-500" : "bg-slate-300"}`} />
                {shortName(a.name)}
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/* ---------------- sağ panel ---------------- */

function SidePanel({ tab, setTab, tasks, agents }:
  { tab: "tasks" | "team"; setTab: (t: "tasks" | "team") => void; tasks: TaskRow[]; agents: Agent[] }) {
  return (
    <aside className="mx-4 mb-44 rounded-2xl border border-line bg-panel/90 p-3 shadow-sm backdrop-blur xl:sticky xl:top-4 xl:mx-0 xl:mr-4 xl:mt-4 xl:mb-0 xl:h-[calc(100vh-11rem)] xl:w-80 xl:overflow-y-auto">
      <div className="mb-3 grid grid-cols-2 gap-1 rounded-lg bg-canvas p-1 text-sm" role="tablist">
        {(["tasks", "team"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`rounded-md py-1.5 ${tab === t ? "bg-panel font-medium shadow-sm" : "text-muted"}`}>
            {t === "tasks" ? `Görevler (${tasks.length})` : "Ekip"}
          </button>
        ))}
      </div>
      {tab === "tasks" ? (
        <ul className="space-y-2">
          {!tasks.length && <li className="p-3 text-sm text-muted">Henüz görev yok. Aşağıdan ekibe bir görev verin.</li>}
          {tasks.slice(0, 30).map((t) => (
            <li key={t.id}>
              <Link href={`/tasks/${t.id}`} className="block rounded-xl border border-line p-3 hover:bg-canvas">
                <div className="flex items-center justify-between gap-2">
                  <StatusBadge status={t.status} />
                  <span className="text-[11px] text-muted">{new Date(t.created_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}</span>
                </div>
                <p className="mt-1.5 line-clamp-2 text-sm font-medium">{t.title}</p>
                <p className="mt-1 text-[11px] text-muted">
                  {t.current_agent ?? "—"}{t.cost_usd ? ` · $${Number(t.cost_usd).toFixed(4)}` : ""}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="space-y-1 text-sm">
          {agents.map((a) => (
            <li key={a.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5">
              <i className={`h-2 w-2 shrink-0 rounded-full ${a.active_tasks ? "animate-pulse bg-emerald-500" : "bg-slate-300"}`} />
              <span className="min-w-0 flex-1 truncate">{a.name}</span>
              <span className="text-[11px] text-muted">{a.active_tasks ? STATUS.running.label : "Boşta"}</span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

/* ---------------- komut çubuğu ---------------- */

function CommandBar({ orgId, agents, target, setTarget, onSent }:
  { orgId: string; agents: Agent[]; target: string; setTarget: (c: string) => void; onSent: (t: TaskRow) => void }) {
  const [cmd, setCmd] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; id?: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (cmd.trim().length < 3) return;
    setBusy(true); setMsg(null);
    const r = await clientApi(`/api/organizations/${orgId}/tasks`, {
      method: "POST", body: JSON.stringify({ command: cmd.trim(), agent_code: target === "ceo" ? null : target }) });
    setBusy(false);
    if (!r.ok) return setMsg({ ok: false, text: r.error ?? "Görev oluşturulamadı" });
    const who = agents.find((a) => a.code === target);
    onSent({ id: r.data.id, title: cmd.trim().slice(0, 120), status: "queued", error: null, created_at: r.data.created_at,
      completed_at: null, current_agent: who?.name ?? null, cost_usd: null });
    setMsg({ ok: true, text: "Görev verildi.", id: r.data.id });
    setCmd("");
  }

  return (
    <form onSubmit={submit}
      className="fixed inset-x-3 bottom-3 z-20 mx-auto max-w-3xl rounded-2xl border border-line bg-panel/95 p-3 shadow-xl backdrop-blur md:left-64 md:pl-3 xl:right-96">
      <textarea value={cmd} onChange={(e) => setCmd(e.target.value)} rows={2} maxLength={4000} aria-label="Görev"
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit(); }}
        placeholder='Ekibine bir görev ver… ör. "Bu hafta YouTube için 5 video fikri bul"'
        className="w-full resize-none bg-transparent text-sm outline-none" />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2 text-sm text-muted">Kime
          <select value={target} onChange={(e) => setTarget(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-line bg-transparent px-2 py-1.5 text-ink sm:max-w-xs">
            <option value="ceo">Genel müdür (CEO) karar versin</option>
            {agents.filter((a) => a.code !== "ceo").map((a) => <option key={a.code} value={a.code}>{a.name}</option>)}
          </select>
        </label>
        <span className="hidden text-xs text-muted sm:inline">Ctrl + Enter</span>
        <button disabled={busy} className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-60">
          {busy ? "Gönderiliyor…" : "Görevi ver →"}
        </button>
      </div>
      {msg && (
        <p role="status" className={`mt-2 text-sm ${msg.ok ? "text-emerald-700" : "text-yt"}`}>
          {msg.text} {msg.id && <Link href={`/tasks/${msg.id}`} className="underline">İlerlemeyi gör</Link>}
        </p>
      )}
    </form>
  );
}
