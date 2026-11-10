import { Inbox } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import type { ApiError } from "../api/client";

export function Card({
  title,
  actions,
  children,
  testId,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section className="card" data-testid={testId}>
      {(title || actions) && (
        <header className="card-head">
          <h2>{title}</h2>
          <div className="card-actions">{actions}</div>
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
  testId,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "up" | "down" | "flat" | "warn";
  testId?: string;
}) {
  return (
    <div className={`stat ${tone ?? ""}`} data-testid={testId}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint !== undefined && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
  testId,
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad" | "info" | "up" | "down";
  testId?: string;
}) {
  return (
    <span className={`badge ${tone}`} data-testid={testId}>
      {children}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <Inbox aria-hidden="true" size={20} />
      <span>{children}</span>
    </div>
  );
}

/** Hata kutusu. Servis kapalıysa (404) bunu açıklayan sakin bir mesaj gösterir. */
export function ErrorBox({ error, what }: { error: ApiError | string | null; what?: string }) {
  if (!error) return null;
  if (typeof error !== "string" && error.unavailable) {
    return (
      <div className="notice" role="status">
        {what ? `${what}: ` : ""}
        {error.message}
      </div>
    );
  }
  return (
    <div className="error" role="alert">
      {typeof error === "string" ? error : error.message}
    </div>
  );
}

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  sort?: (row: T) => number | string | null;
  align?: "left" | "right" | "center";
  width?: string;
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  empty = "Kayıt yok",
  initialSort,
  testId,
  onRowClick,
  maxRows,
}: {
  rows: T[] | undefined;
  columns: Column<T>[];
  rowKey: (row: T, index: number) => string;
  empty?: ReactNode;
  initialSort?: { key: string; desc: boolean };
  testId?: string;
  onRowClick?: (row: T) => void;
  maxRows?: number;
}) {
  const [sort, setSort] = useState(initialSort);
  const sorted = useMemo(() => {
    const list = [...(rows ?? [])];
    const column = columns.find((c) => c.key === sort?.key);
    if (column?.sort && sort) {
      const get = column.sort;
      list.sort((a, b) => {
        const x = get(a);
        const y = get(b);
        if (x === y) return 0;
        if (x === null) return 1;
        if (y === null) return -1;
        const result = x < y ? -1 : 1;
        return sort.desc ? -result : result;
      });
    }
    return maxRows ? list.slice(0, maxRows) : list;
  }, [rows, columns, sort, maxRows]);

  if (!rows || rows.length === 0) return <Empty>{empty}</Empty>;
  return (
    <div className="table-wrap">
      <table data-testid={testId}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                style={{ textAlign: c.align ?? "left", width: c.width }}
                className={c.sort ? "sortable" : undefined}
                onClick={() =>
                  c.sort &&
                  setSort((s) => ({ key: c.key, desc: s?.key === c.key ? !s.desc : true }))
                }
              >
                {c.label}
                {sort?.key === c.key ? (sort.desc ? " ▾" : " ▴") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={onRowClick ? "clickable" : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} style={{ textAlign: c.align ?? "left" }}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Tabs<K extends string>({
  value,
  options,
  onChange,
  testId,
}: {
  value: K;
  options: { key: K; label: string }[];
  onChange: (key: K) => void;
  testId?: string;
}) {
  return (
    <div className="tabs" role="tablist" data-testid={testId}>
      {options.map((o) => (
        <button
          key={o.key}
          role="tab"
          aria-selected={o.key === value}
          className={o.key === value ? "active" : ""}
          onClick={() => onChange(o.key)}
          type="button"
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Onay penceresi (tarayıcı confirm() masaüstü görünümünde güvenilir değildir). */
export function Confirm({
  open,
  title,
  children,
  confirmLabel = "Onayla",
  danger,
  phrase,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  /** Verilirse kullanıcının bu ifadeyi birebir yazması gerekir. */
  phrase?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [typed, setTyped] = useState("");
  if (!open) return null;
  const ok = !phrase || typed.trim() === phrase;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal">
        <h3>{title}</h3>
        <div className="modal-body">{children}</div>
        {phrase && (
          <label className="field">
            <span>
              Onaylamak için yazın: <code>{phrase}</code>
            </span>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
          </label>
        )}
        <div className="modal-actions">
          <button
            type="button"
            onClick={() => {
              setTyped("");
              onCancel();
            }}
          >
            Vazgeç
          </button>
          <button
            type="button"
            className={danger ? "danger" : "primary"}
            disabled={!ok}
            onClick={() => {
              setTyped("");
              onConfirm();
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function Disclaimer() {
  return (
    <p className="disclaimer">
      Bu uygulama yatırım tavsiyesi vermez ve kazanç garantisi yoktur. Geçmiş ve sanal sonuçlar
      gelecekteki sonuçları göstermez.
    </p>
  );
}
