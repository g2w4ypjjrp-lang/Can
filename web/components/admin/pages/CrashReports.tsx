"use client";

import { Bug } from "lucide-react";
import { useState } from "react";

import { useApi } from "@/components/ApiContext";
import { AdminPage, EmptyState, Feedback, StatusPill, inputClass, useAdminAction, useAdminQuery, type PillTone } from "@/components/admin/kit";
import { dateTime } from "@/lib/admin";

interface Report {
  fingerprint: string;
  app: "engine" | "desktop";
  component: string;
  error_type: string;
  message: string;
  stack: string;
  first_version: string;
  last_version: string;
  os: string;
  occurrences: number;
  status: Status;
  first_seen: string;
  last_seen: string;
}

type Status = "new" | "seen" | "fixed" | "ignored";

const STATUS: Record<Status, { label: string; tone: PillTone }> = {
  new: { label: "Yeni", tone: "warn" },
  seen: { label: "İnceleniyor", tone: "info" },
  fixed: { label: "Düzeltildi", tone: "success" },
  ignored: { label: "Yok sayıldı", tone: "neutral" },
};

const APP_LABEL = { engine: "İşlem motoru", desktop: "Masaüstü arayüzü" };

function ReportCard({ report, onChanged }: { report: Report; onChanged: () => void }) {
  const api = useApi();
  const action = useAdminAction();
  const short = report.fingerprint.slice(0, 8);

  async function change(status: Status) {
    const ok = await action.run(() => api.patch(`/admin/v1/crash-reports/${report.fingerprint}`, { status }));
    if (ok) onChanged();
  }

  return (
    <li className="rounded-3xl border border-border bg-surface p-5 shadow-sm" data-testid={`crash-${short}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-sm font-semibold text-fg">
            {report.error_type} <span className="font-normal text-muted">· {report.component}</span>
          </p>
          <p className="mt-1 break-words text-sm text-fg">{report.message || "(mesaj yok)"}</p>
          <p className="mt-1 text-xs text-muted">
            {APP_LABEL[report.app]} · {report.occurrences} kez · sürüm {report.first_version}
            {report.last_version !== report.first_version ? ` → ${report.last_version}` : ""} · {report.os} · son{" "}
            {dateTime(report.last_seen)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill tone={STATUS[report.status].tone} testId={`crash-status-${short}`}>
            {STATUS[report.status].label}
          </StatusPill>
          <label htmlFor={`durum-${short}`} className="visually-hidden">
            {report.error_type} durumu
          </label>
          <select
            id={`durum-${short}`}
            value={report.status}
            onChange={(e) => void change(e.target.value as Status)}
            disabled={action.pending}
            className={`${inputClass} w-40`}
          >
            {(Object.keys(STATUS) as Status[]).map((s) => (
              <option key={s} value={s}>
                {STATUS[s].label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-medium text-accent-text">Kod satırları</summary>
        <pre className="mt-2 max-h-80 overflow-auto rounded-xl bg-surface-2 p-3 font-mono text-xs leading-relaxed text-fg">{report.stack || "(yok)"}</pre>
      </details>
      <Feedback error={action.error} />
    </li>
  );
}

export function CrashReports() {
  const [filter, setFilter] = useState<Status | "">("");
  const reports = useAdminQuery<Report[]>(`/admin/v1/crash-reports${filter ? `?status=${filter}` : ""}`);
  return (
    <AdminPage
      title="Hata raporları"
      lead="Hata raporlarını açan kullanıcıların uygulamalarından gelir. Aynı hata tek satırda sayılır. Kişisel veri (ad, e-posta, kullanıcı klasörü, IP, lisans ve borsa anahtarları) uygulamada ve sunucuda ayıklanır; IP adresi saklanmaz."
      actions={
        <label className="flex items-center gap-2 text-sm text-fg">
          Durum
          <select value={filter} onChange={(e) => setFilter(e.target.value as Status | "")} className={`${inputClass} w-40`}>
            <option value="">Tümü</option>
            {(Object.keys(STATUS) as Status[]).map((s) => (
              <option key={s} value={s}>
                {STATUS[s].label}
              </option>
            ))}
          </select>
        </label>
      }
    >
      <Feedback error={reports.error} />
      {reports.data && reports.data.length === 0 ? (
        <EmptyState icon={Bug} title="Rapor yok">
          Bu süzgeçle eşleşen hata raporu yok.
        </EmptyState>
      ) : null}
      {reports.data && reports.data.length > 0 ? (
        <ul className="space-y-4">
          {reports.data.map((r) => (
            <ReportCard key={r.fingerprint} report={r} onChanged={reports.reload} />
          ))}
        </ul>
      ) : null}
    </AdminPage>
  );
}
