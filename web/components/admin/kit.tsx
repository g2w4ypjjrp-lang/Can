"use client";

import { Inbox, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { useApi } from "@/components/ApiContext";
import { Notice } from "@/components/ui";
import { ApiError, NETWORK_ERROR } from "@/lib/api";

/** GET isteği + yeniden yükleme. */
export function useAdminQuery<T>(path: string | null) {
  const api = useApi();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(() => {
    if (!path) return;
    setLoading(true);
    api
      .get<T>(path)
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : NETWORK_ERROR))
      .finally(() => setLoading(false));
  }, [api, path]);
  useEffect(() => {
    load();
  }, [load]);
  return { data, error, loading, reload: load };
}

/** Durum değiştiren istek: bekleme, hata ve başarı mesajı. */
export function useAdminAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const run = useCallback(async <T,>(action: () => Promise<T>, success?: string): Promise<T | undefined> => {
    setPending(true);
    setError(null);
    setMessage(null);
    try {
      const result = await action();
      if (success) setMessage(success);
      return result;
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : NETWORK_ERROR);
      return undefined;
    } finally {
      setPending(false);
    }
  }, []);
  return { pending, error, message, run, setMessage };
}

export function Feedback({ error, message }: { error: string | null; message?: string | null }) {
  return (
    <>
      {error ? (
        <Notice tone="danger" role="alert">
          {error}
        </Notice>
      ) : null}
      {message ? (
        <Notice tone="success" role="status">
          {message}
        </Notice>
      ) : null}
    </>
  );
}

/** Sayfa başlığı ve gövdesi. Her yönetim sayfasında tek h1. */
export function AdminPage({
  title,
  lead,
  children,
  actions,
  eyebrow,
}: {
  title: string;
  lead?: string;
  children: ReactNode;
  actions?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {eyebrow ? <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent-text">{eyebrow}</p> : null}
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-fg sm:text-3xl">{title}</h1>
          {lead ? <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted">{lead}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}

/** Başlıklı panel kartı. */
export function AdminCard({
  title,
  description,
  actions,
  children,
  className = "",
  id,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  const headingId = id ?? (title ? `kart-${title.toLocaleLowerCase("tr-TR").replace(/[^a-z0-9ğüşöçı]+/g, "-")}` : undefined);
  return (
    <section aria-labelledby={title ? headingId : undefined} className={`rounded-3xl border border-border bg-surface p-5 shadow-sm sm:p-6 ${className}`}>
      {title || actions ? (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title ? (
              <h2 id={headingId} className="font-semibold text-fg">
                {title}
              </h2>
            ) : null}
            {description ? <p className="mt-0.5 text-sm text-muted">{description}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** Gösterge kartı: büyük değer, açıklama, isteğe bağlı küçük grafik. */
export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  chart,
  testId,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon: LucideIcon;
  chart?: ReactNode;
  testId?: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-border bg-surface p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-muted">{label}</p>
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-surface-2 text-accent-text">
          <Icon aria-hidden="true" className="h-4 w-4" />
        </span>
      </div>
      <p className="tabular mt-3 truncate text-3xl font-semibold tracking-tight text-fg" data-testid={testId}>
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
      {chart ? <div className="mt-3">{chart}</div> : null}
    </div>
  );
}

const PILL_TONES = {
  neutral: "border-border bg-surface-2 text-fg",
  info: "border-info-border bg-info-bg text-info-fg",
  success: "border-success-border bg-success-bg text-success-fg",
  warn: "border-warn-border bg-warn-bg text-warn-fg",
  danger: "border-danger-border bg-danger-bg text-danger-fg",
};

export type PillTone = keyof typeof PILL_TONES;

/** Durum etiketi: renk + yazı (renk tek başına anlam taşımaz). */
export function StatusPill({ tone = "neutral", children, testId }: { tone?: PillTone; children: ReactNode; testId?: string }) {
  return (
    <span data-testid={testId} className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${PILL_TONES[tone]}`}>
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
      {children}
    </span>
  );
}

const ORDER_TONES: Record<string, PillTone> = {
  fulfilled: "success",
  paid: "info",
  pending: "warn",
  failed: "danger",
  cancelled: "neutral",
  refunded: "neutral",
  partially_refunded: "warn",
};
const LICENSE_TONES: Record<string, PillTone> = {
  active: "success",
  sold: "info",
  ready_for_sale: "neutral",
  generated: "neutral",
  frozen: "warn",
  expired: "neutral",
  cancelled: "danger",
};

export function orderTone(status: string): PillTone {
  return ORDER_TONES[status] ?? "neutral";
}
export function licenseTone(status: string): PillTone {
  return LICENSE_TONES[status] ?? "neutral";
}

export function EmptyState({ icon: Icon = Inbox, title, children }: { icon?: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-border px-6 py-12 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2 text-muted">
        <Icon aria-hidden="true" className="h-5 w-5" />
      </span>
      <p className="mt-4 font-semibold text-fg">{title}</p>
      {children ? <div className="mt-1 max-w-sm text-sm text-muted">{children}</div> : null}
    </div>
  );
}

/** Yüklenirken yer tutucu (düzen kaymasın). */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <span aria-hidden="true" className={`skeleton block rounded-lg ${className}`} />;
}

export function Table({ caption, head, children }: { caption: string; head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-3xl border border-border bg-surface shadow-sm">
      <table className="w-full min-w-[640px] text-left text-sm">
        <caption className="visually-hidden">{caption}</caption>
        <thead className="border-b border-border bg-surface-2/60 text-xs uppercase tracking-wide text-muted">
          <tr>
            {head.map((h, i) => (
              <th key={`${h}-${i}`} scope="col" className="px-4 py-3 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border text-fg [&>tr]:transition-colors [&>tr:hover]:bg-surface-2/50">{children}</tbody>
      </table>
    </div>
  );
}

export const cell = "px-4 py-3 align-top";
export const inputClass =
  "block w-full rounded-xl border border-border-strong/70 bg-surface px-3 py-2 text-sm text-fg shadow-sm transition-colors placeholder:text-muted hover:border-border-strong " +
  "focus-visible:border-accent-text focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring";
export const smallButton =
  "inline-flex items-center justify-center gap-1.5 rounded-xl border border-border-strong/40 bg-surface px-3 py-1.5 text-xs font-semibold text-fg shadow-sm transition-colors " +
  "hover:border-border-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-text disabled:opacity-50";
export const primaryButton =
  "shine inline-flex items-center justify-center gap-1.5 rounded-xl bg-brand px-3.5 py-2 text-sm font-semibold text-white shadow-glow transition " +
  "hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-text disabled:opacity-60";

/** Güncel TOTP kodu alanı (hassas işlemler). */
export function TotpInput({ id, label = "Doğrulama kodu (TOTP)", required = true }: { id: string; label?: string; required?: boolean }) {
  return (
    <label htmlFor={id} className="block text-sm font-medium text-fg">
      {label}
      <input
        id={id}
        name="code"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        maxLength={6}
        required={required}
        className={`mt-1 ${inputClass} w-36 font-mono tracking-[0.3em]`}
      />
    </label>
  );
}
