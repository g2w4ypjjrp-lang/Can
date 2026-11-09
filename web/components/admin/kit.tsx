"use client";

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

export function AdminPage({ title, lead, children, actions }: { title: string; lead?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
          {lead ? <p className="mt-1 max-w-3xl text-sm text-muted">{lead}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}

export function Table({ caption, head, children }: { caption: string; head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="w-full min-w-[640px] text-left text-sm">
        <caption className="visually-hidden">{caption}</caption>
        <thead className="bg-surface-2 text-fg">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="px-3 py-2.5 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border text-fg">{children}</tbody>
      </table>
    </div>
  );
}

export const cell = "px-3 py-2.5 align-top";
export const inputClass =
  "block w-full rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm text-fg focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";
export const smallButton =
  "rounded-lg border border-border-strong/50 bg-surface px-3 py-1.5 text-xs font-semibold text-fg hover:bg-surface-2 disabled:opacity-50";

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
        className={`mt-1 ${inputClass} w-36 font-mono tracking-widest`}
      />
    </label>
  );
}
