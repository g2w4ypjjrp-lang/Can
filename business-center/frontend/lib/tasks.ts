export type TaskRow = { id: string; title: string; status: string; error: string | null; created_at: string;
  completed_at: string | null; current_agent: string | null; cost_usd: string | null };

export const STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "Sırada", cls: "bg-slate-100 text-slate-700" },
  running: { label: "Çalışıyor", cls: "bg-indigo-100 text-indigo-800" },
  waiting_qc: { label: "Kalite kontrolde", cls: "bg-amber-100 text-amber-800" },
  waiting_approval: { label: "Onay bekliyor", cls: "bg-orange-100 text-orange-800" },
  completed: { label: "Tamamlandı", cls: "bg-emerald-100 text-emerald-800" },
  failed: { label: "Başarısız", cls: "bg-rose-100 text-rose-800" },
  cancelled: { label: "İptal", cls: "bg-slate-100 text-slate-500" },
  pending: { label: "Bekliyor", cls: "bg-slate-100 text-slate-600" },
  done: { label: "Bitti", cls: "bg-emerald-100 text-emerald-800" },
  skipped: { label: "Atlandı", cls: "bg-slate-100 text-slate-500" },
  succeeded: { label: "Başarılı", cls: "bg-emerald-100 text-emerald-800" },
};

export const ACTIVE = new Set(["queued", "running", "waiting_qc", "waiting_approval"]);
